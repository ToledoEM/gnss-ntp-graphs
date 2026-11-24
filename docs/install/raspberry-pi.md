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
| `/var/lib/gnss-ntp-graphs/samples.db` | SQLite history |
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

## Uninstall

```bash
sudo ./install.sh --uninstall              # keeps /var/lib/gnss-ntp-graphs
sudo ./install.sh --uninstall --purge      # deletes the collected history too
```

Uninstall stops and removes the service, the lighttpd alias, `/opt/gnss-ntp-graphs` and `/etc/gnss-ntp-graphs`.
