"""Filesystem safety/retention checks; no sensor or root access required."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

here = Path(__file__).resolve().parent
source = here / 'sensor' / 'sensor_maintenance.py'
if not source.exists():
    source = here.parent / 'scripts' / 'sensor_maintenance.py'
spec = importlib.util.spec_from_file_location('sensor_maintenance', source)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'log'
        self.root.mkdir()
        self.now = 2_000_000_000
        self.sessions = []
        for index in range(6):
            session = self.root / ('00000000-0000-0000-0000-%012d' % index)
            session.mkdir()
            file = session / 'rosout.log'
            file.write_bytes(b'x' * 1024)
            stamp = self.now - (10 + index) * 86400
            os.utime(file, (stamp, stamp))
            os.utime(session, (stamp, stamp))
            self.sessions.append(session)

    def tearDown(self):
        self.temp.cleanup()

    def test_age_prunes_only_closed_runs_and_keeps_three_newest(self):
        plan, total = m.log_plan(self.root, self.now,
                                 opened={self.sessions[4] / 'rosout.log'})
        self.assertEqual({s[0] for s in plan}, {self.sessions[3], self.sessions[5]})
        self.assertGreater(total, 0)
        self.assertTrue(all(p.exists() for p in self.sessions))

    def test_top_level_logs_are_bounded_without_removing_open_files(self):
        logs = []
        for i in range(6):
            p = self.root / ('rostopic_%d.log' % i)
            p.write_text('diagnostic')
            stamp = self.now - (10 + i) * 86400
            os.utime(p, (stamp, stamp))
            logs.append(p)
        plan, _ = m.log_plan(self.root, self.now, opened={logs[4]})
        selected = {p for _, files, _ in plan for p, _ in files}
        self.assertIn(logs[5], selected)
        self.assertNotIn(logs[4], selected)
        self.assertTrue(all(p not in selected for p in logs[:3]))

    def test_budget_prunes_oldest_even_if_young_without_touching_newest(self):
        plan, _ = m.log_plan(self.root, self.now - 15 * 86400,
                            opened=set(), budget=1)
        self.assertEqual([s[0] for s in plan], self.sessions[:2:-1])

    def test_non_session_recordings_are_not_candidates(self):
        extra = self.root / 'recordings'
        extra.mkdir()
        (extra / 'important.bag').write_bytes(b'x' * 4096)
        plan, _ = m.log_plan(self.root, self.now, opened=set(), budget=1)
        self.assertNotIn(extra, [s[0] for s in plan])
        recording = self.sessions[5] / 'important.bag'
        recording.write_bytes(b'keep me')
        plan, _ = m.log_plan(self.root, self.now, opened=set(), budget=1)
        self.assertTrue(plan)
        self.assertTrue(all(recording not in [p for p, _ in files] for _, files, _ in plan))

    def test_editor_refuses_dependency_removal_or_installs(self):
        for plan in ('Remv code [1]\nRemv ros-noetic-roscpp [1]',
                     'Remv code [1]\nInst unrelated-package [1]'):
            with patch.object(m, 'run', return_value=plan):
                with self.assertRaises(RuntimeError):
                    m.remove_editor(apply=True)

    def test_buffer_rollback_refuses_invalid_backup_without_writes(self):
        state = Path(self.temp.name) / 'state'
        state.mkdir()
        (state / 'receive-buffer-before.json').write_text('{"bad-key": 1}')
        with patch.object(m, 'STATE', state), patch.object(m, 'run') as run:
            with self.assertRaises(ValueError):
                m.restore_buffers()
            run.assert_not_called()

    @unittest.skipUnless(hasattr(os, 'O_NOFOLLOW'), 'Linux cleanup execution check')
    def test_apply_removes_only_closed_log_files_and_is_idempotent(self):
        recording = self.sessions[5] / 'important.bag'
        recording.write_bytes(b'preserve recording')
        with patch.object(m, 'LOG_ROOT', self.root), patch.object(m, 'open_log_paths', return_value=set()), \
                patch.object(m.time, 'time', return_value=self.now):
            lock = str(Path(self.temp.name) / 'cleanup.lock')
            preview = m.prune_logs(False, lock)
            self.assertTrue((self.sessions[4] / 'rosout.log').exists())
            self.assertGreater(preview['eligible_sessions'], 0)
            applied = m.prune_logs(True, lock)
            self.assertGreater(applied['deleted_sessions'], 0)
            self.assertTrue(recording.exists())
            self.assertTrue((self.sessions[0] / 'rosout.log').exists())
            self.assertEqual(m.prune_logs(True, lock)['deleted_sessions'], 0)

    def test_buffer_install_preserves_stronger_settings_and_original_backup(self):
        state, config = Path(self.temp.name) / 'state', Path(self.temp.name) / 'receive.conf'
        def fake_run(args):
            return '33554432' if args[-1] == 'net.core.rmem_max' else '8388608'
        with patch.object(m, 'STATE', state), patch.object(m, 'BUFFER_FILE', config), \
                patch.object(m, 'run', side_effect=fake_run):
            original = {'net.core.rmem_max': 212992, 'net.core.rmem_default': 212992}
            m.install_buffers(original)
            m.install_buffers()
        self.assertIn('net.core.rmem_max = 33554432', config.read_text())
        self.assertIn('net.core.rmem_default = 8388608', config.read_text())
        self.assertIn('212992', (state / 'receive-buffer-before.json').read_text())

    def test_latest_and_symlinks_are_preserved(self):
        try:
            (self.root / 'latest').symlink_to(self.sessions[5], target_is_directory=True)
        except OSError:
            self.skipTest('Symlinks require developer mode on this Windows host')
        plan, _ = m.log_plan(self.root, self.now, opened=set())
        self.assertNotIn(self.sessions[5], [s[0] for s in plan])
        with self.assertRaises(ValueError):
            m.log_plan(self.root / 'latest', self.now, opened=set())


if __name__ == '__main__':
    unittest.main()
