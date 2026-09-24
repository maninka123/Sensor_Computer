import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "transport_supervisor.py"
SPEC = importlib.util.spec_from_file_location("transport_supervisor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeGraph:
    def __init__(self, clients):
        self.clients = clients
        self.topics = {"/merged_colored_cloud"}

    def system_state(self):
        return [[], [], []]

    def direct_native_clients(self, _state):
        return list(self.clients)


class FakeServices:
    def __init__(self, bridge_running):
        self.running = bridge_running
        self.actions = []

    def bridge_running(self):
        return self.running

    def set_bridge(self, running):
        self.running = running
        self.actions.append(running)


class SupervisorTests(unittest.TestCase):
    def status_path(self, directory):
        return str(Path(directory) / "status.json")

    def test_stops_bridge_after_stable_native_client(self):
        client = {
            "node": "/surface_receiver",
            "host": "10.20.0.10",
            "topics": ["/merged_colored_cloud"],
        }
        with tempfile.TemporaryDirectory() as directory:
            services = FakeServices(True)
            supervisor = MODULE.Supervisor(
                FakeGraph([client]), services, 15.0, 45.0, self.status_path(directory)
            )
            self.assertEqual(supervisor.step(now=0)["active_transport"], "handoff")
            supervisor.step(now=14.9)
            self.assertEqual(services.actions, [])
            status = supervisor.step(now=15.0)
            self.assertEqual(services.actions, [False])
            self.assertEqual(status["active_transport"], "tcpros")

    def test_restores_bridge_after_native_client_is_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            services = FakeServices(False)
            supervisor = MODULE.Supervisor(
                FakeGraph([]), services, 15.0, 45.0, self.status_path(directory)
            )
            self.assertEqual(supervisor.step(now=100)["active_transport"], "fallback_wait")
            supervisor.step(now=144.9)
            self.assertEqual(services.actions, [])
            status = supervisor.step(now=145.0)
            self.assertEqual(services.actions, [True])
            self.assertEqual(status["active_transport"], "rosbridge")

    def test_client_change_restarts_stability_window(self):
        first = [{"node": "/one", "host": "10.20.0.10", "topics": ["/camera/image_raw"]}]
        second = [{"node": "/two", "host": "10.20.0.11", "topics": ["/camera/image_raw"]}]
        with tempfile.TemporaryDirectory() as directory:
            graph = FakeGraph(first)
            services = FakeServices(True)
            supervisor = MODULE.Supervisor(
                graph, services, 15.0, 45.0, self.status_path(directory)
            )
            supervisor.step(now=0)
            graph.clients = second
            supervisor.step(now=10)
            supervisor.step(now=24.9)
            self.assertEqual(services.actions, [])
            supervisor.step(now=25)
            self.assertEqual(services.actions, [False])


if __name__ == "__main__":
    unittest.main()
