#!/usr/bin/env python3
"""Prefer remote native TCPROS clients and retain ROSBridge as a fallback."""

import argparse
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlparse
import xmlrpc.client


BRIDGE_SERVICE = "node-pc-rosbridge.service"
BRIDGE_NODE = "/rosbridge_websocket"
CALLER_ID = "/node_pc_transport_supervisor"


def env_float(name, default):
    try:
        value = float(os.environ.get(name, default))
    except ValueError as exc:
        raise SystemExit("%s must be numeric" % name) from exc
    if value <= 0:
        raise SystemExit("%s must be positive" % name)
    return value


def configured_topics():
    value = os.environ.get(
        "TRANSPORT_NATIVE_TOPICS", "/merged_colored_cloud,/camera/image_raw"
    )
    topics = tuple(item.strip() for item in value.split(",") if item.strip())
    if not topics:
        raise SystemExit("TRANSPORT_NATIVE_TOPICS must contain at least one topic")
    return topics


def rpc_value(result, operation):
    if not isinstance(result, (list, tuple)) or len(result) != 3 or result[0] != 1:
        raise RuntimeError("%s failed: %r" % (operation, result))
    return result[2]


def host_addresses(host):
    addresses = set()
    try:
        for item in socket.getaddrinfo(host, None):
            addresses.add(item[4][0])
    except socket.gaierror:
        pass
    return addresses


def local_addresses():
    addresses = {"127.0.0.1", "::1"}
    configured = os.environ.get("ROS_IP", "").strip()
    if configured:
        addresses.add(configured)
    addresses.update(host_addresses(socket.gethostname()))
    addresses.update(host_addresses("localhost"))
    return addresses


def remote_host(node_uri):
    return urlparse(node_uri).hostname or ""


def is_remote_uri(node_uri, local):
    host = remote_host(node_uri)
    if not host:
        return False
    resolved = host_addresses(host) or {host}
    return resolved.isdisjoint(local)


class RosGraph:
    def __init__(self, master_uri, topics):
        self.master = xmlrpc.client.ServerProxy(master_uri, allow_none=True)
        self.topics = set(topics)
        self.local = local_addresses()

    def system_state(self):
        return rpc_value(self.master.getSystemState(CALLER_ID), "getSystemState")

    def all_nodes(self, state):
        nodes = set()
        for group in state:
            for _name, members in group:
                nodes.update(members)
        return nodes

    def node_uri(self, node):
        return rpc_value(self.master.lookupNode(CALLER_ID, node), "lookupNode")

    def direct_native_clients(self, state=None):
        if state is None:
            state = self.system_state()
        subscribed_topics = {}
        for topic, nodes in state[1]:
            if topic not in self.topics:
                continue
            for node in nodes:
                if node != BRIDGE_NODE:
                    subscribed_topics.setdefault(node, set()).add(topic)

        clients = []
        for node, topics in sorted(subscribed_topics.items()):
            try:
                uri = self.node_uri(node)
                if not is_remote_uri(uri, self.local):
                    continue
                node_rpc = xmlrpc.client.ServerProxy(uri, allow_none=True)
                bus_info = rpc_value(node_rpc.getBusInfo(CALLER_ID), "getBusInfo")
                confirmed = {
                    entry[4]
                    for entry in bus_info
                    if len(entry) >= 6
                    and entry[2] == "i"
                    and str(entry[3]).upper() == "TCPROS"
                    and bool(entry[5])
                    and entry[4] in topics
                }
                if confirmed:
                    clients.append(
                        {
                            "node": node,
                            "host": remote_host(uri),
                            "topics": sorted(confirmed),
                        }
                    )
            except (OSError, RuntimeError, xmlrpc.client.Error) as exc:
                logging.debug("Could not verify native node %s: %s", node, exc)
        return clients


class ServiceManager:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run

    def bridge_running(self):
        return subprocess.run(
            ["systemctl", "is-active", "--quiet", BRIDGE_SERVICE], check=False
        ).returncode == 0

    def set_bridge(self, running):
        action = "start" if running else "stop"
        logging.info("%s %s", action, BRIDGE_SERVICE)
        if self.dry_run:
            return
        subprocess.run(["systemctl", action, BRIDGE_SERVICE], check=True)


def atomic_status_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def transport_label(bridge_running, native_clients):
    if native_clients and bridge_running:
        return "handoff"
    if native_clients:
        return "tcpros"
    if bridge_running:
        return "rosbridge"
    return "fallback_wait"


class Supervisor:
    def __init__(self, graph, services, stable_seconds, lost_seconds, status_file):
        self.graph = graph
        self.services = services
        self.stable_seconds = stable_seconds
        self.lost_seconds = lost_seconds
        self.status_file = status_file
        self.native_since = None
        self.native_lost_since = None
        self.last_clients = []

    def step(self, now=None):
        now = time.monotonic() if now is None else now
        error = None
        state = None
        clients = []
        try:
            state = self.graph.system_state()
            clients = self.graph.direct_native_clients(state)
        except (OSError, RuntimeError, xmlrpc.client.Error) as exc:
            error = "ROS master unavailable: %s" % exc
            logging.warning(error)

        bridge_running = self.services.bridge_running()
        if error is None and clients:
            self.native_lost_since = None
            if self.native_since is None or clients != self.last_clients:
                self.native_since = now
            stable_for = now - self.native_since
            if bridge_running and stable_for >= self.stable_seconds:
                self.services.set_bridge(False)
                bridge_running = self.services.bridge_running()
        elif error is None:
            self.native_since = None
            if self.native_lost_since is None:
                self.native_lost_since = now
            lost_for = now - self.native_lost_since
            if not bridge_running and lost_for >= self.lost_seconds:
                self.services.set_bridge(True)
                bridge_running = self.services.bridge_running()

        self.last_clients = clients
        payload = {
            "active_transport": transport_label(bridge_running, clients),
            "bridge_running": bridge_running,
            "native_clients": clients,
            "native_stable_for_seconds": (
                round(now - self.native_since, 1) if self.native_since is not None else 0.0
            ),
            "native_lost_for_seconds": (
                round(now - self.native_lost_since, 1)
                if self.native_lost_since is not None
                else 0.0
            ),
            "stable_threshold_seconds": self.stable_seconds,
            "fallback_threshold_seconds": self.lost_seconds,
            "monitored_topics": sorted(self.graph.topics),
            "error": error,
            "updated_unix": time.time(),
        }
        atomic_status_write(self.status_file, payload)
        return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[transport] %(levelname)s: %(message)s")

    poll_seconds = env_float("TRANSPORT_POLL_SECONDS", 2)
    stable_seconds = env_float("TRANSPORT_NATIVE_STABLE_SECONDS", 15)
    lost_seconds = env_float("TRANSPORT_NATIVE_LOST_SECONDS", 45)
    status_file = os.environ.get(
        "TRANSPORT_STATUS_FILE", "/run/node-pc-transport-status.json"
    )
    master_uri = os.environ.get("ROS_MASTER_URI", "http://127.0.0.1:11311")
    supervisor = Supervisor(
        RosGraph(master_uri, configured_topics()),
        ServiceManager(args.dry_run),
        stable_seconds,
        lost_seconds,
        status_file,
    )

    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopped:
        supervisor.step()
        if args.once:
            break
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
