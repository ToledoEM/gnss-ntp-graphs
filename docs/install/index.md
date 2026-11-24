# Install

The collector is plain Python 3.11 with no third-party packages. Pick where it runs and which source it reads, then follow one of the install pages.

## Choosing a source

| Source | Use it on | Reads |
|---|---|---|
| `local` | The Pi with the GPS receiver | `chronyc -c tracking/sources/sourcestats` and `chronyc ntpdata`, or `ntpq -c rv` and `ntpq -pn`, plus gpsd on port 2947 |
| `bridge` | Any other machine, or Docker | `ntpq_crv.json`, `ntpq_pn.json` and `gps.json` from the bridge's web root |

The `local` source only runs monitoring commands. It never changes chrony, ntpd or gpsd settings, and gpsd accepts a second client, so it runs fine next to the bridge. The `bridge` source sends HTTP GET requests and nothing else.

Both sources produce the same fields. Offsets, jitter and delays are in milliseconds, frequency and wander in parts per million, and the offset sign follows `ntpq` (source minus local clock).

With `local`, the [daemon logs](../configuration/daemon-logs.md) option can add finer offset data to the Stats tab. The bridge does not publish those logs, so `bridge` always uses polled samples.

## Install methods

| Method | Page | Typical use |
|---|---|---|
| `install.sh` with systemd | [Raspberry Pi or Debian](raspberry-pi.md) | The time server itself, or a Debian box on the same network |
| Docker image | [Docker](docker.md) | A home server that already runs containers |
| Your own web server | [Web server](web-server.md) | Serving the page from lighttpd, nginx or the built-in server |

## Requirements

- Python 3.11 or newer. Raspberry Pi OS Bookworm ships 3.11.
- For `local`: `chronyc` or `ntpq` on the path, and gpsd listening on `127.0.0.1:2947` (both configurable).
- For `bridge`: network access to the bridge's web root, for example `http://192.168.1.50/`.
