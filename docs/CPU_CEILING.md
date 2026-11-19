# Persistent CPU ceiling

Run on **each compatible sensor PC**, from its **Sensor_Computer** folder.
The tested CPU layout is ROCK 5A; the read-only probe rejects unsupported settings.

## Install

```bash
python3 scripts/cpu_ceiling.py probe
sudo python3 scripts/cpu_ceiling.py install
```

Sets a **1.008 GHz maximum** for the four big cores (`policy4`/`policy6`).
`cmp-cpu-ceiling.service` reapplies it before acquisition at boot, without Windows.
Clocks can scale lower; cooling governors, minimums and thermal protection are preserved.

## Device 5 results

| Measurement | Before: 408/600 MHz, ~2 min | 1.008 GHz, 15 min |
|---|---:|---:|
| Point-cloud FPS | 0.910 | **1.000** |
| Data rate | 36.34 Mb/s | **41.20 Mb/s** |
| Mean receive latency | 2.87 s | **2.11 s** |
| Zero-FPS samples | 1 / 23 | **0 / 172** |

Sampled peak: **83.2 Â°C**. Restoring the old limits brought back dropouts
(5 / 31 samples). These sequential, unequal-duration tests cover Device 5 only;
check streaming and temperature on every device. Its actual reboot check is pending.

## Check after reboot

```bash
systemctl is-active cmp-cpu-ceiling.service
cat /sys/devices/system/cpu/cpufreq/policy{4,6}/scaling_max_freq
```

Expect `active` and `1008000` kHz, or a lower thermal limit.
Re-enable the separate 3 h/10 min cooling schedule after reboot.

**Undo:** `sudo systemctl disable --now cmp-cpu-ceiling.service`, then reboot
during planned downtime. Disabling alone leaves the live ceilings in place.

**Code:** [installer](../scripts/cpu_ceiling.py) Â· [tests](../tests/test_cpu_ceiling.py).
