# gnss-ntp-graphs

History graphs for a GPS-disciplined NTP server, in the style of graphs1090. A small Python collector records chrony or ntpd and gpsd readings into SQLite and writes JSON files that a static page draws.

It runs alongside [GPSNTPHomeBridge](https://github.com/ToledoEM/GPSNTPHomeBridge), the bridge that feeds the same server into Home Assistant, and leaves it untouched. It needs Python 3.11 or newer and no pip packages.

## Sources

| Source | Use it on | Reads |
|---|---|---|
| `local` | The Pi with the GPS receiver | `chronyc -c tracking/sources/sourcestats`, `chronyc ntpdata`, or `ntpq -c rv` and `ntpq -pn`, plus gpsd on port 2947 |
| `bridge` | Any other machine, or Docker | `ntpq_crv.json`, `ntpq_pn.json` and `gps.json` from the bridge |

Both sources use the bridge's field mapping, so the graphs look the same either way. The `local` source runs only monitoring commands and opens a second gpsd client, which gpsd supports. It never writes to the bridge's web root or to `/opt/ntphomebridge`.

## Install on a Pi or Debian host

```bash
git clone https://github.com/ToledoEM/gnss-ntp-graphs
cd gnss-ntp-graphs
sudo ./install.sh                                   # local source if chronyc/ntpq is present
sudo ./install.sh --source bridge --bridge-url http://192.168.1.50/
```

If lighttpd is installed, as it is with the bridge's full install, the graphs appear at `http://<host>/graphs/`. If not, the collector serves them on port 8080. Use `--web none` to serve `/var/lib/gnss-ntp-graphs/www` yourself; `deploy/nginx-gnss-ntp-graphs.conf` has an nginx example.

Uninstall with `sudo ./install.sh --uninstall`. Add `--purge` to delete the collected data as well.

## Configuration

The config file is `/etc/gnss-ntp-graphs/config.toml`. `deploy/config.toml` lists every key with its default, so a file of your own only needs the keys you change. Restart the service after editing it. Any key can also be set from the environment as `GNG_<SECTION>_<KEY>`, with lists comma-separated (`GNG_WEB_SECTIONS=ntp,peers`). An unknown key or a bad value stops the collector with a message naming the key.

The page options live under `[web]` and follow graphs1090's `default` file where it has an equivalent:

| Key | graphs1090 | Purpose |
|---|---|---|
| `title`, `header` | `WWW_TITLE`, `WWW_HEADER` | Tab title and page heading, plus an optional line under it |
| `repo_url`, `docs_url` | | Links behind the GitHub and documentation icons in the header; empty hides an icon |
| `theme` | `colorscheme` | `auto`, `light` or `dark`. Viewers can switch with the theme button, and the browser remembers their choice |
| `palette` | | Plot colours, from the [ColorBrewer](https://colorbrewer2.org) qualitative schemes: `Accent`, `Dark2`, `Paired` (default), `Pastel1`, `Pastel2`, `Set1`, `Set2`, `Set3`. A graph uses as many colours as it has lines; lines beyond the scheme's largest set are dashed |
| `colourblind_safe` | | Limits colours to the sets ColorBrewer rates colourblind safe: `Paired` up to 4 colours, `Dark2` and `Set2` 3 colours. Further lines are dashed |
| `layout` | | `tabs` shows one section at a time; `single` puts all sections on one page |
| `sections`, `hide_graphs` | `HIDE_SYSTEM` | Which sections appear and in what order, and which graphs to leave out |
| `graph_height`, `columns`, `font_size` | `graph_size`, `all_large`, `font_size` | Graph height, graphs per row and base font size |
| `timezone` | `TZ` | `local`, `UTC` or an IANA name for the time axis |
| `offset_unit` | | `ms` or `us` for offsets, jitter, delay and dispersion |
| `offset_lines` | `max_messages_line` | Dashed reference lines on the offset graph, in ms |
| `ranges`, `default_range` | | Which range buttons appear, and which one opens first |
| `offset_warn_ms`, `offset_bad_ms`, `stale_warn_s`, `stale_bad_s` | | Limits for the status colours in the header |
| `max_peers`, `hide_peers` | | How many peers are drawn, and which ones never are |

Fixed y-axis limits go in one table per graph, in the unit the graph shows (graphs1090 `ul_*` and `ll_*`):

```toml
[graphs.offset]
y_min = -0.05
y_max = 0.05
```

`[intervals] export` is the equivalent of `DRAW_INTERVAL`. graphs1090's settings for disk, network, temperature, scatter and airspy graphs have no equivalent, because this tool does not graph the host system.

## Docker (bridge source)

```bash
docker build -t gnss-ntp-graphs .
docker run -d --name gnss-ntp-graphs -p 8080:8080 \
  -e GNG_SOURCE_BRIDGE_URL=http://192.168.1.50/ \
  -v gnss-ntp-graphs:/data gnss-ntp-graphs
```

To use the `local` source on a host running chronyd, build with `--build-arg WITH_CHRONYC=1` and run with `--network host -e GNG_SOURCE_TYPE=local`.

## Pages

- NTP: offset, system and clock jitter, frequency and wander, root delay and dispersion, stratum.
- Peers: offset, delay, jitter and reach for each source, plus a table of the current peers.
- GNSS: satellites used and visible, used satellites per constellation, average signal strength, DOP, and a sky plot of the latest SKY report.
- Stats: ntpviz-style summaries over 24 hours and 7 days. For offset, jitter, frequency, root delay, root dispersion and GNSS quality, each window shows the 1st, 5th, 50th, 95th and 99th percentiles, the 90% and 98% ranges, the mean and the standard deviation. The page also has an offset histogram, the Allan deviation of offset, and per-peer offset, delay and the share of polls where reach was 377.

Time ranges run from 2 hours to 1 year. The collector keeps raw samples for 7 days, 5-minute averages for 90 days and hourly averages for 3 years.

## Finer statistics from daemon logs

With polled samples the Allan deviation starts at a 60 s tau. Both daemons can log every clock update, which gives finer data and history from before you installed this tool. Neither does so by default, and this tool will not change your daemon config, so turn it on yourself:

- chrony: add `log tracking` and `logdir /var/log/chrony` to `chrony.conf`, restart chronyd, then set `chrony_tracking = "/var/log/chrony/tracking.log"` under `[logs]`.
- ntpd/ntpsec: add `statsdir /var/log/ntpstats/` and `statistics loopstats` to `ntp.conf`, restart ntpd, then set `ntpd_loopstats = "/var/log/ntpstats/loopstats"` under `[logs]`.

The collector also reads rotated files (`loopstats.20261124`, `tracking.log.1`) but skips compressed ones.

## Development

```bash
uv run pytest
uv run python -m gnss_ntp_graphs -c deploy/config.toml once   # one poll and export
```

Turn on the commit-message hook once per clone with `git config core.hooksPath .githooks`. It rejects messages that break the rules in `.githooks/commit-lint.sh`: Conventional Commits, a subject of at most 72 characters, and a body of at most 5 lines.
