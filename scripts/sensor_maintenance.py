#!/usr/bin/env python3
"""Explicit sensor maintenance; status and prune-logs default to read-only."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time

LOG_ROOT = Path('/home/rock/.ros/log')
STATE = Path('/var/lib/cmp-maintenance')
BUFFER_FILE = Path('/etc/sysctl.d/90-cmp-camera-receive.conf')
BUFFER_VALUES = {'net.core.rmem_max': 16777216, 'net.core.rmem_default': 4194304}
UUID = re.compile(r'^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$')


def run(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:] or result.stdout[-1500:])
    return result.stdout.strip()


def write_owned(path, text):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing symlink: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.cmp-tmp')
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def open_log_paths(root, proc=Path('/proc')):
    paths = set()
    for pid in proc.iterdir():
        if not pid.name.isdigit():
            continue
        try:
            for fd in (pid / 'fd').iterdir():
                try:
                    target = Path(os.readlink(str(fd)))
                    if root in target.parents:
                        paths.add(target)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
    return paths


def log_plan(root=LOG_ROOT, now=None, opened=None, budget=512 * 1024**2, days=7):
    root = Path(root)
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError('ROS log root must not traverse symlinks')
    if not root.exists():
        return [], 0
    opened = open_log_paths(root) if opened is None else opened
    latest = (root / 'latest').resolve()
    sessions, total = [], 0
    for session in root.iterdir():
        if session.is_symlink() or not session.is_dir() or not UUID.fullmatch(session.name):
            continue
        files, all_files = [], []
        for folder, dirs, names in os.walk(str(session), followlinks=False):
            dirs[:] = [d for d in dirs if not Path(folder, d).is_symlink()]
            for name in names:
                p = Path(folder, name)
                info = p.lstat()
                if stat.S_ISREG(info.st_mode):
                    all_files.append((p, info))
                    # Never delete recordings or unrelated files even inside a ROS run.
                    if re.search(r'\.log(?:\.\d+)?$', name):
                        files.append((p, info))
        size = sum(getattr(i, 'st_blocks', (i.st_size + 511) // 512) * 512 for _, i in files)
        newest = max([session.stat().st_mtime] + [i.st_mtime for _, i in all_files])
        protected = session == latest or any(session in p.parents for p in opened)
        sessions.append((newest, session, files, size, protected))
        total += size
    sessions.sort(key=lambda s: s[0], reverse=True)
    # Preserve at least three newest runs, the latest symlink target and all open runs.
    protected_paths = {s[1] for s in sessions[:3]}
    root_logs = []
    for p in root.iterdir():
        if p.is_symlink() or not re.search(r'\.log(?:\.\d+)?$', p.name):
            continue
        info = p.lstat()
        if stat.S_ISREG(info.st_mode):
            size = getattr(info, 'st_blocks', (info.st_size + 511) // 512) * 512
            root_logs.append((info.st_mtime, p, [(p, info)], size, p in opened))
            total += size
    root_logs.sort(key=lambda s: s[0], reverse=True)
    protected_paths.update(s[1] for s in root_logs[:3])
    sessions.extend(root_logs)
    sessions.sort(key=lambda s: s[0], reverse=True)
    now = time.time() if now is None else now
    remaining, selected = total, []
    for newest, session, files, size, protected in reversed(sessions):
        if protected or session in protected_paths or not files:
            continue
        if newest < now - days * 86400 or remaining > budget:
            selected.append((session, files, size))
            remaining -= size
    return selected, total


def prune_logs(apply=False, lock_path='/tmp/node-pc-ros-log-cleanup.lock'):
    import fcntl
    if LOG_ROOT.resolve() != LOG_ROOT or LOG_ROOT.is_symlink():
        raise ValueError('Unexpected ROS log directory')
    # Shared with the original startup cleanup to avoid simultaneous deletion.
    try:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666)
        os.fchmod(lock_fd, 0o666)
    with os.fdopen(lock_fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'skipped': 'Another cleanup is running'}
        selected, total = log_plan(LOG_ROOT)
        deleted, freed = 0, 0
        opened = open_log_paths(LOG_ROOT) if apply else set()
        for index, (session, files, size) in enumerate(selected):
            if apply:
                # Recheck activity and identities immediately before each deletion.
                if index and index % 1000 == 0:
                    opened = open_log_paths(LOG_ROOT)
                if session == (LOG_ROOT / 'latest').resolve() or session in opened or any(session in p.parents for p in opened):
                    continue
                for path, info in files:
                    if path.resolve() != path or not LOG_ROOT in path.parents:
                        raise ValueError('Log path escaped its root')
                    current = path.lstat()
                    if (current.st_ino, current.st_size, current.st_mtime_ns) != (info.st_ino, info.st_size, info.st_mtime_ns):
                        raise RuntimeError('Log changed during cleanup; refusing deletion')
                for path, _ in files:
                    path.unlink()
                for folder, dirs, names in os.walk(str(session), topdown=False, followlinks=False):
                    try:
                        Path(folder).rmdir()
                    except OSError:
                        pass
                deleted += 1
                freed += size
        return dict(apply=apply, before_bytes=total, eligible_sessions=len(selected),
                    eligible_bytes=sum(s[2] for s in selected), deleted_sessions=deleted,
                    freed_bytes=freed, target_bytes=512 * 1024**2, retention_days=7,
                    note='Active runs and the newest three runs are protected; target is not a hard cap.')


def install_buffers(original=None):
    previous = {k: int(run(['sysctl', '-n', k])) for k in BUFFER_VALUES}
    STATE.mkdir(parents=True, exist_ok=True)
    backup = STATE / 'receive-buffer-before.json'
    if not backup.exists():
        write_owned(backup, json.dumps(previous if original is None else original, indent=2) + '\n')
    # Preserve any stronger administrator tuning.
    values = {k: max(v, previous[k]) for k, v in BUFFER_VALUES.items()}
    write_owned(BUFFER_FILE, '# CMP camera receive headroom; existing sockets update when reopened.\n' +
                ''.join('{} = {}\n'.format(k, v) for k, v in values.items()))
    return {'settings': run(['sysctl', '-p', str(BUFFER_FILE)]), 'backup': str(backup)}


def restore_buffers():
    previous = json.loads((STATE / 'receive-buffer-before.json').read_text())
    if set(previous) != set(BUFFER_VALUES) or any(type(v) is not int or not 4096 <= v <= 2**30 for v in previous.values()):
        raise ValueError('Invalid receive-buffer backup')
    if BUFFER_FILE.is_symlink() or (BUFFER_FILE.exists() and not BUFFER_FILE.read_text().startswith('# CMP camera receive headroom;')):
        raise ValueError('Receive-buffer file was changed; review it manually')
    result = run(['sysctl', '-w'] + ['{}={}'.format(k, previous[k]) for k in BUFFER_VALUES])
    if BUFFER_FILE.exists():
        BUFFER_FILE.unlink()
    return {'settings': result, 'note': 'Existing sockets retain their buffers until reopened.'}


def install_logs(source):
    write_owned('/usr/local/lib/cmp-maintenance/sensor_maintenance.py', source)
    write_owned('/etc/systemd/journald.conf.d/60-cmp-retention.conf',
                '[Journal]\nSystemMaxUse=256M\nSystemKeepFree=1G\nSystemMaxFileSize=32M\n'
                'RuntimeMaxUse=64M\nMaxRetentionSec=7day\n')
    # Reuse the existing daily timer; no second cleanup schedule.
    if not Path('/etc/systemd/system/node-pc-log-cleanup.service').exists():
        write_owned('/etc/systemd/system/node-pc-log-cleanup.service',
                    '[Unit]\nDescription=Prune closed ROS logs\n[Service]\nType=oneshot\n')
    write_owned('/etc/systemd/system/node-pc-log-cleanup.service.d/60-cmp-retention.conf',
                '[Service]\nUser=root\nExecStart=\nExecStart=/usr/bin/python3 '
                '/usr/local/lib/cmp-maintenance/sensor_maintenance.py prune-logs --apply\n'
                'Nice=19\nIOSchedulingClass=idle\n')
    if not Path('/etc/systemd/system/node-pc-log-cleanup.timer').exists():
        write_owned('/etc/systemd/system/node-pc-log-cleanup.timer',
                    '[Unit]\nDescription=Daily closed ROS log cleanup\n[Timer]\nOnBootSec=15min\n'
                    'OnUnitActiveSec=1d\n[Install]\nWantedBy=timers.target\n')
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', 'node-pc-log-cleanup.timer'])
    # Restart journald as one transaction; never stop it separately (stream FDs survive).
    run(['systemctl', 'restart', 'systemd-journald.service'])
    run(['journalctl', '--rotate'])
    vacuum = run(['journalctl', '--vacuum-size=256M'])
    return dict(journal=run(['journalctl', '--disk-usage']), vacuum=vacuum,
                ros=prune_logs(apply=True))


def remove_editor(apply=False):
    plan = run(['apt-get', '-s', 'remove', 'code'])
    removals = re.findall(r'^Remv (\S+)', plan, re.MULTILINE)
    if removals not in ([], ['code']) or re.search(r'^Inst ', plan, re.MULTILINE):
        raise RuntimeError('Expected only code to be removed; inspect apt plan: ' + plan)
    extensions = Path('/home/rock/.vscode/extensions')
    if extensions.is_symlink() or extensions.resolve() != extensions:
        raise ValueError('Unexpected extensions path')
    # Refuse an active local editor; do not terminate any user process.
    for comm in Path('/proc').glob('[0-9]*/comm'):
        try:
            if comm.read_text().strip() in ('code', 'code-insiders', 'electron'):
                raise RuntimeError('Close the sensor editor before removal')
        except FileNotFoundError:
            pass
    if not apply:
        return dict(plan=plan, extensions=str(extensions))
    removed = run(['apt-get', '-y', 'remove', 'code'])
    if extensions.exists():
        shutil.rmtree(str(extensions))
    return dict(package=removed, extensions_removed=str(extensions),
                preserved='Workspace, ROS/SDKs, ~/.codex, VS Code user settings; no autoremove/purge.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'install-buffers', 'restore-buffers', 'install-logs',
                                         'prune-logs', 'remove-editor', 'clean-package-cache'])
    parser.add_argument('--apply', action='store_true', help='Required for removal/cache cleanup')
    args = parser.parse_args()
    if args.action == 'status':
        result = dict(disk=shutil.disk_usage('/')._asdict(),
                      buffers={k: run(['sysctl', '-n', k]) for k in BUFFER_VALUES},
                      journal=run(['journalctl', '--disk-usage']))
    elif args.action == 'install-buffers':
        result = install_buffers()
    elif args.action == 'restore-buffers':
        result = restore_buffers()
    elif args.action == 'install-logs':
        result = install_logs(Path(__file__).read_text())
    elif args.action == 'prune-logs':
        result = prune_logs(args.apply)
    elif args.action == 'remove-editor':
        result = remove_editor(args.apply)
    else:
        result = {'applied': args.apply, 'output': run(['apt-get', 'clean']) if args.apply else 'Dry run: apt-get clean'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
