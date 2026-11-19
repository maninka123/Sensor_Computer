import runpy
from pathlib import Path
import tempfile
import unittest

here = Path(__file__).resolve().parent
source = next(p for p in [here / 'sensor/cpu_ceiling.py', here.parent / 'scripts/cpu_ceiling.py'] if p.exists())
agent = runpy.run_path(str(source))
BaseCpu = agent['CpuCeiling']


class CeilingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['policy0', 'policy4', 'policy6']:
            p = self.root / name
            p.mkdir()
            for file, value in dict(scaling_min_freq='408000', scaling_max_freq='2400000',
                                    scaling_governor='ondemand',
                                    scaling_available_frequencies='408000 600000 1008000 1608000 2400000').items():
                (p / file).write_text(value)
        class StrictCpu(BaseCpu):
            def write(cpu, directory, value):
                cpu.writes.append((directory.name, value))
                super(StrictCpu, cpu).write(directory, value)
        self.cpu = StrictCpu(self.root)
        self.cpu.writes = []
        self.policies = ['policy4', 'policy6']

    def test_only_selected_ceilings_change_and_cooling_governor_is_preserved(self):
        (self.root / 'policy4/scaling_governor').write_text('powersave')
        self.cpu.apply(self.policies, 1008000)
        self.assertEqual(self.cpu.read(self.root / 'policy0', 'scaling_max_freq'), '2400000')
        self.assertEqual(self.cpu.read(self.root / 'policy4', 'scaling_min_freq'), '408000')
        self.assertEqual(self.cpu.read(self.root / 'policy4', 'scaling_governor'), 'powersave')
        self.assertTrue(all(r['maximum_khz'] == 1008000 for r in self.cpu.readings(self.policies)))

    def test_unsupported_policy_is_rejected_before_any_write(self):
        (self.root / 'policy6/scaling_available_frequencies').write_text('408000 600000')
        with self.assertRaisesRegex(RuntimeError, 'not advertised'):
            self.cpu.apply(self.policies, 1008000)
        self.assertEqual(self.cpu.writes, [])

    def test_custom_minimum_is_not_lowered_to_make_the_profile_fit(self):
        (self.root / 'policy6/scaling_min_freq').write_text('1608000')
        with self.assertRaisesRegex(RuntimeError, 'minimum exceeds'):
            self.cpu.apply(self.policies, 1008000)
        self.assertEqual(self.cpu.writes, [])

    def test_invalid_paths_duplicates_and_values_are_rejected_without_writes(self):
        for policies, maximum in [(['../policy4'], 1008000), (['policy4', 'policy4'], 1008000),
                                  ([], 1008000), (self.policies, 0), (self.policies, True)]:
            with self.assertRaises(ValueError):
                self.cpu.apply(policies, maximum)
        self.assertEqual(self.cpu.writes, [])

    def test_missing_boot_policy_times_out_without_changing_other_policies(self):
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            self.cpu.apply(['policy4', 'policy8'], 1008000, wait_seconds=0)
        self.assertEqual(self.cpu.writes, [])

    def test_thermal_cap_below_requested_ceiling_is_accepted_without_forcing_clocks(self):
        def thermal_write(p, value):
            self.cpu.writes.append((p.name, value))
            (p / 'scaling_max_freq').write_text('600000')
        self.cpu.write = thermal_write
        self.cpu.apply(self.policies, 1008000)
        self.assertEqual(self.cpu.writes, [('policy4', 1008000), ('policy6', 1008000)])
        self.assertTrue(all(r['maximum_khz'] == 600000 for r in self.cpu.readings(self.policies)))

    def test_delayed_qos_readback_is_allowed(self):
        original_read = self.cpu.read
        pending = {}
        def delayed_write(p, value):
            pending[p.name] = [2, value]
        def delayed_read(p, name):
            if name == 'scaling_max_freq' and p.name in pending:
                item = pending[p.name]
                if item[0] == 0:
                    (p / name).write_text(str(item[1]))
                else:
                    item[0] -= 1
            return original_read(p, name)
        self.cpu.write, self.cpu.read = delayed_write, delayed_read
        self.cpu.apply(self.policies, 1008000)
        self.assertTrue(all(r['maximum_khz'] == 1008000 for r in self.cpu.readings(self.policies)))

    def test_failed_readback_is_reported(self):
        self.cpu.write = lambda p, value: None
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            self.cpu.apply(self.policies, 1008000, verify_seconds=0)

    def test_a_write_failure_does_not_skip_the_other_policy(self):
        original = self.cpu.write
        def fail_first(p, value):
            if p.name == 'policy4':
                raise OSError('simulated permission failure')
            original(p, value)
        self.cpu.write = fail_first
        with self.assertRaisesRegex(RuntimeError, 'permission failure'):
            self.cpu.apply(self.policies, 1008000, verify_seconds=0)
        self.assertEqual(self.cpu.read(self.root / 'policy6', 'scaling_max_freq'), '1008000')

    def test_unit_orders_profile_before_acquisition_without_restarting_it(self):
        unit = agent['unit_text'](self.policies, 1008000)
        self.assertIn('Before=node-pc.service', unit)
        self.assertIn('ondemand.service', unit)
        self.assertIn('WantedBy=multi-user.target', unit)
        self.assertNotIn('ExecStop=', unit)
        with self.assertRaises(ValueError):
            agent['unit_text'](['policy4;reboot'], 1008000)


if __name__ == '__main__':
    unittest.main()
