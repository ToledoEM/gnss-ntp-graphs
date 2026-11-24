# Raspberry Pi or Debian

`install.sh` installs the collector as a systemd service on Debian or Raspberry Pi OS. Run it as root from a clone of the repository.

```bash
git clone https://github.com/ToledoEM/gnss-ntp-graphs
cd gnss-ntp-graphs
sudo ./install.sh                                    # local source if chronyc or ntpq is present
sudo ./install.sh --source bridge --bridge-url http://192.168.1.50/
```

When the script finishes it prints the address of the graphs.

## Options

| Option | Default | Effect |
|---|---|---|
| `--source bridge\|local` | `local` if `chronyc` or `ntpq` is on the path, else `bridge` | Data source written to the new config file |
| `--bridge-url URL` | `http://127.0.0.1/` | Bridge base URL, used with `--source bridge` |
| `--web lighttpd\|builtin\|none` | `lighttpd` if installed, else `builtin` | How the page is served (see below) |
| `--uninstall` | | Removes the service, code and config, keeps the data |
| `--purge` | | With `--uninstall`, also deletes `/var/lib/gnss-ntp-graphs` |

## What the script does

The script installs python3 if it is missing and touches nothing else. It does not change chrony, ntpd, gpsd or GPSNTPHomeBridge. A second run upgrades the code and keeps your config file.

## Installed files

| Path | Contents |
|---|---|
| `/opt/gnss-ntp-graphs/gnss_ntp_graphs/` | The Python package |
| `/etc/gnss-ntp-graphs/config.toml` | Configuration, see [Configuration](../configuration/index.md) |
| `/etc/systemd/system/gnss-ntp-graphs.service` | systemd unit |
| `/var/lib/gnss-ntp-graphs/samples.db` | SQLite history, see [backing up](../configuration/collector.md#backing-up) |
| `/var/lib/gnss-ntp-graphs/www/` | Static page and `data/*.json` |
| `/etc/lighttpd/conf-available/89-gnss-ntp-graphs.conf` | lighttpd alias, only with `--web lighttpd` |

## The service

The unit runs `python3 -m gnss_ntp_graphs -c /etc/gnss-ntp-graphs/config.toml run` as the unprivileged user `gnssgraphs`. It starts after the network, chrony, ntpd, ntpsec and gpsd units, and restarts 10 seconds after a failure.

systemd sandboxing keeps the collector read-only everywhere except its state directory: `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `PrivateDevices=yes`, `NoNewPrivileges=yes` and `ReadWritePaths=/var/lib/gnss-ntp-graphs`. If you point `[logs]` at a daemon log, that file only needs to be readable by `gnssgraphs`.

Common commands:

```bash
sudo systemctl status gnss-ntp-graphs
sudo systemctl restart gnss-ntp-graphs     # after editing config.toml
journalctl -u gnss-ntp-graphs -f           # follow the log
```

## CPU temperature

The collector records the CPU temperature every `[intervals] host` seconds (60 by default) and graphs it against the frequency correction. Set `[source] host_temp = false` to turn it off.

Where the reading comes from depends on where the collector runs.

| Collector runs on | Temperature of | Read from |
|---|---|---|
| The GPS Pi (`local` or `bridge`) | The GPS Pi | `/sys/class/thermal/thermal_zone0/temp` under the service, `vcgencmd measure_temp` when run by hand |
| Another machine or Docker (`bridge`) | The GPS Pi, if the bridge publishes `cpu_temp.json` | `<bridge_url>/cpu_temp.json` |
| Another machine, bridge without `cpu_temp.json` | That machine, if it has a sensor | Its own thermal zone |

The service runs with `PrivateDevices=yes`, which hides `/dev/vchiq`, so `vcgencmd` cannot run inside it. The kernel thermal zone is the same sensor and stays readable. Check both by hand on the Pi:

```bash
vcgencmd measure_temp                          # temp=48.3'C
cat /sys/class/thermal/thermal_zone0/temp      # 48312 (millidegrees)
```

### Publishing the temperature from the bridge

GPSNTPHomeBridge does not publish a temperature file itself. To get the GPS Pi's temperature into a collector on another machine, add a timer on the Pi that writes `cpu_temp.json` into the bridge's web root (`/var/www/html` by default):

```json
{"timestamp": 1795535340, "cpu_temp": 48.3}
```

`timestamp` is Unix seconds or an ISO 8601 string. The collector ignores a file older than 5 minutes, so a stopped timer shows as a gap rather than a flat line.

`/usr/local/bin/cpu-temp-json`:

```bash
#!/bin/sh
# Write the CPU temperature as cpu_temp.json for gnss-ntp-graphs
out=/var/www/html/cpu_temp.json
milli=$(cat /sys/class/thermal/thermal_zone0/temp) || exit 1
printf '{"timestamp": %s, "cpu_temp": %s.%03d}\n' "$(date +%s)" "$((milli / 1000))" "$((milli % 1000))" > "$out.tmp"
mv "$out.tmp" "$out"
```

Make it executable and run it every minute from root's crontab:

```bash
sudo chmod 755 /usr/local/bin/cpu-temp-json
(sudo crontab -l 2>/dev/null; echo '* * * * * /usr/local/bin/cpu-temp-json') | sudo crontab -
```

Check it with `curl http://<bridge>/cpu_temp.json`. The collector picks the file up on its next poll; no restart is needed.

## Uninstall

```bash
sudo ./install.sh --uninstall              # keeps /var/lib/gnss-ntp-graphs
sudo ./install.sh --uninstall --purge      # deletes the collected history too
```

Uninstall stops and removes the service, the lighttpd alias, `/opt/gnss-ntp-graphs` and `/etc/gnss-ntp-graphs`.
