#!/usr/bin/env python3
"""Explicit CPU ceilings, including optional systemd boot persistence. Python 3.8+."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path('/sys/devices/system/cpu/cpufreq')
SCRIPT = Path('/usr/local/lib/cmp-cpu-profile/cpu_ceiling.py')
UNIT_PATH = Path('/etc/systemd/system/cmp-cpu-ceiling.service')
UNIT = UNIT_PATH.name
MARKER = '# Managed by Central Monitoring Platform CPU ceiling'


class CpuCeiling:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def directories(self, policies):
        if not policies or len(set(policies)) != len(policies):
            raise ValueError('Choose distinct CPU policies')
        if any(not re.fullmatch(r'policy[0-9]+', p) for p in policies):
            raise ValueError('Invalid CPU policy name')
        return [self.root / p for p in policies]

    def read(self, directory, name):
        return (directory / name).read_text().strip()

    def write(self, directory, value):
        # This is an explicit requested ceiling, never a saved thermal reading.
        (directory / 'scaling_max_freq').write_text(str(value))

    def readings(self, policies):
        return [dict(policy=p.name, minimum_khz=int(self.read(p, 'scaling_min_freq')),
                     maximum_khz=int(self.read(p, 'scaling_max_freq')),
                     governor=self.read(p, 'scaling_governor'))
                for p in self.directories(policies)]

    def validate(self, policies, maximum, wait_seconds=0):
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
            raise ValueError('CPU ceiling must be a positive integer in kHz')
        directories = self.directories(policies)
        deadline = time.monotonic() + wait_seconds
        while not all(p.is_dir() for p in directories):
            if time.monotonic() >= deadline:
                raise RuntimeError('Selected CPU policies are unavailable')
            time.sleep(0.2)
        # Check every policy before any write. Custom floors remain untouched.
        for p in directories:
            available = [int(v) for v in self.read(p, 'scaling_available_frequencies').split()]
            if maximum not in available:
                raise RuntimeError('CPU ceiling is not advertised on ' + p.name)
            if int(self.read(p, 'scaling_min_freq')) > maximum:
                raise RuntimeError('Existing CPU minimum exceeds the requested ceiling on ' + p.name)
        return directories

    def apply(self, policies, maximum, wait_seconds=15, verify_seconds=2):
        directories = self.validate(policies, maximum, wait_seconds)
        failures = []
        for p in directories:
            try:
                self.write(p, maximum)
            except OSError as exc:
                failures.append(p.name + ': ' + str(exc))
        # Frequency QoS readback can update asynchronously. Thermal constraints
        # may make the effective maximum lower than our requested ceiling.
        deadline = time.monotonic() + verify_seconds
        while any(int(self.read(p, 'scaling_max_freq')) > maximum for p in directories):
            if time.monotonic() >= deadline:
                failures.append('Effective CPU ceilings were not confirmed')
                break
            time.sleep(0.05)
        if failures:
            raise RuntimeError('; '.join(failures))
        return dict(ok=True, requested_maximum_khz=maximum, policies=self.readings(policies))


def unit_text(policies, maximum):
    CpuCeiling().directories(policies)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise ValueError('Invalid CPU ceiling')
    return '\n'.join([
        MARKER, '[Unit]', 'Description=Persistent CPU ceiling for sensor acquisition',
        'After=systemd-modules-load.service ondemand.service cpufrequtils.service sysfsutils.service',
        'Before=node-pc.service', '', '[Service]', 'Type=oneshot',
        'ExecStart=/usr/bin/python3 ' + str(SCRIPT) + ' apply --maximum-khz ' + str(maximum) +
        ' --policies ' + ' '.join(policies),
        'RemainAfterExit=yes', 'TimeoutStartSec=25', '', '[Install]',
        'WantedBy=multi-user.target', ''])


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(' '.join(args[:3]) + ': ' + result.stderr[-1500:])
    return result.stdout.strip()


def install_profile(policies, maximum, source):
    if os.geteuid() != 0:
        raise RuntimeError('Install with sudo')
    CpuCeiling().validate(policies, maximum)
    text = unit_text(policies, maximum)
    # Refuse to overwrite an unrelated or different deployment automatically.
    files = [(SCRIPT, source), (UNIT_PATH, text)]
    for path, content in files:
        if path.is_symlink() or (path.exists() and path.read_text() != content):
            raise RuntimeError('Existing file differs; review before replacing: ' + str(path))
    if SCRIPT.parent.is_symlink():
        raise RuntimeError('Unexpected CPU profile directory symlink')
    created = []
    enabled_here = False
    previously_enabled = subprocess.run(['systemctl', 'is-enabled', '--quiet', UNIT],
                                       capture_output=True).returncode == 0
    try:
        SCRIPT.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        for path, content in files:
            if not path.exists():
                with path.open('x', encoding='utf8') as stream:
                    created.append(path)
                    stream.write(content)
                path.chmod(0o644)
        run(['systemd-analyze', 'verify', str(UNIT_PATH)])
        run(['systemctl', 'daemon-reload'])
        enabled_here = not previously_enabled
        run(['systemctl', 'enable', '--now', UNIT])
        run(['systemctl', 'is-enabled', UNIT])
        run(['systemctl', 'is-active', UNIT])
    except Exception:
        if enabled_here:
            subprocess.run(['systemctl', 'disable', '--now', UNIT], capture_output=True)
        for path in reversed(created):
            path.unlink()
        subprocess.run(['systemctl', 'daemon-reload'], capture_output=True)
        raise
    return dict(ok=True, installed=True, enabled=True, service=UNIT,
                requested_maximum_khz=maximum, policies=CpuCeiling().readings(policies),
                ordering=run(['systemctl', 'show', UNIT, '--property=Before,After,ActiveState,SubState']),
                files=[str(p) for p, _ in files])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['probe', 'apply', 'install'])
    parser.add_argument('--maximum-khz', type=int, default=1008000)
    parser.add_argument('--policies', nargs='+', default=['policy4', 'policy6'])
    args = parser.parse_args()
    try:
        if args.action == 'install':
            result = install_profile(args.policies, args.maximum_khz, Path(__file__).read_text())
        elif args.action == 'apply':
            result = CpuCeiling().apply(args.policies, args.maximum_khz)
        else:
            CpuCeiling().validate(args.policies, args.maximum_khz)
            result = dict(ok=True, policies=CpuCeiling().readings(args.policies))
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps(dict(ok=False, error=str(exc))))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
