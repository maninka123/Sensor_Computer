# Persistent CPU ceiling

Install once on each sensor PC; Windows is not needed at boot.

For a compatible ROCK 5A, Device 5's tested profile is:

```bash
python3 scripts/cpu_ceiling.py probe --maximum-khz 1008000 --policies policy4 policy6
sudo python3 scripts/cpu_ceiling.py install --maximum-khz 1008000 --policies policy4 policy6
systemctl is-enabled cmp-cpu-ceiling.service
systemctl status cmp-cpu-ceiling.service
```

Choose each board's actual policy names and an advertised frequency in kHz.
The probe rejects unsupported frequencies and incompatible minimums before any
write. Other hardware needs its own load/temperature test.

The installer adds `/usr/local/lib/cmp-cpu-profile/cpu_ceiling.py` and
`cmp-cpu-ceiling.service`. It runs after CPU initialization and before
`node-pc.service`. It does not restart acquisition or edit ROS, camera, LiDAR
or network configuration.

Only maximum frequency requests change. Governors, minimums, other policies
and kernel thermal protection stay in place. On Device 5, the four big cores
scale up to 1.008 GHz normally; governor-only cooling can select powersave
within the same limits. This is a ceiling, not a fixed clock.

Device 5 completed 15 minutes at approximately 1 FPS, 41.2 Mb/s and 2.11 s
mean receive latency, with no recorded zero-FPS samples, reconnects, fusion-drop
warnings or watchdog relaunches. Sampled temperature peaked at 83.2 °C.
The service is installed/enabled; an actual reboot check is pending.

After reboot, inspect `/sys/devices/system/cpu/cpufreq/policy{4,6}/scaling_max_freq`;
expect 1008000 or a lower effective thermal limit. Check the service journal
with `journalctl -u cmp-cpu-ceiling.service -b`.
The separate 3 h/10 min cooling schedule still needs re-enabling after reboot.

Disable future application with `sudo systemctl disable --now cmp-cpu-ceiling.service`,
then reboot to restore the board's normal startup settings. Disabling alone
does not raise live ceilings.

Tests: `python3 -B -m unittest discover -s tests -p test_cpu_ceiling.py`.
