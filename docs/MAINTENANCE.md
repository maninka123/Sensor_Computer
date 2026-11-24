# Sensor maintenance

Run from the Sensor_Computer checkout on a compatible Ubuntu sensor PC
(the ROS log path is `/home/rock/.ros/log`). CPU settings remain the separate
[tested 1.008 GHz profile](CPU_CEILING.md).

```bash
sudo python3 scripts/sensor_maintenance.py status
sudo python3 scripts/sensor_maintenance.py install-buffers
sudo python3 scripts/sensor_maintenance.py install-logs
sudo python3 scripts/sensor_maintenance.py remove-editor          # preview
sudo python3 scripts/sensor_maintenance.py remove-editor --apply
sudo python3 scripts/sensor_maintenance.py clean-package-cache --apply
```

In the Central_Monitoring_Platform repository, use `scripts/sensor/sensor_maintenance.py`.

| Change | Effect |
|---|---|
| Receive buffers | Persistent default **4 MiB**, maximum **16 MiB**; preserves stronger existing settings. Existing sockets change only when reopened. No pipeline restart. |
| System journal | **256 MiB**, **7 days**, **1 GiB** free-space reserve. Restarts journald as one transaction; leaves acquisition running. |
| ROS logs | Reuses the daily timer. Deletes closed `.log`/`.log.N` files older than **7 days**, or oldest closed runs above a **512 MiB** target. Includes top-level topic logs. Preserves open logs/runs, `latest`, the newest three runs/topic logs and non-log files. Protected runs can exceed the target. |
| Editor | Removes only the `code` package and `/home/rock/.vscode/extensions` after checking the APT plan and inactive editor. No autoremove or purge. Keeps workspace, ROS/SDKs, `.codex` data and user settings. |
| Package cache | Removes downloaded installation archives; installed packages stay installed. |

Installed files: `/etc/sysctl.d/90-cmp-camera-receive.conf`,
`/etc/systemd/journald.conf.d/60-cmp-retention.conf`,
`/etc/systemd/system/node-pc-log-cleanup.service.d/60-cmp-retention.conf`,
`/usr/local/lib/cmp-maintenance/sensor_maintenance.py`.
The existing pipeline source/configuration and CPU profile are unchanged.
Log pruning permanently removes old diagnostic logs; export needed evidence first.

Check `sudo ss -uanmp`: the camera UDP socket (Device 5: port 8881) should show
`rb4194304` after reopening. Compare deltas of `Udp: RcvbufErrors` in
`/proc/net/snmp` over equal intervals, alongside FPS/latency and camera timeouts.
Do not compare per-socket drop counters across socket recreation.

Buffer rollback: `sudo python3 scripts/sensor_maintenance.py restore-buffers`.
It restores the original values saved in `/var/lib/cmp-maintenance/receive-buffer-before.json`
and removes only the dedicated buffer file; existing sockets update when reopened.
To revert retention, remove the two dedicated retention drop-ins, run
`sudo systemctl daemon-reload` and `sudo systemctl restart systemd-journald`.
Deleted logs cannot be recovered. VS Code can be installed again when needed.

References: [Linux receive-buffer settings](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/net.html),
[journald stream-safe restart](https://www.freedesktop.org/software/systemd/man/latest/systemd-journald.service.html#Stream%20logging).
