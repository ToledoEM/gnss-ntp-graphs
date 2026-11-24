# Changelog

## Unreleased

- CPU temperature of the collector's host, read with `vcgencmd measure_temp` or the kernel thermal zone, with either source type. New NTP graph of temperature against frequency, Stats scatter plots of frequency and offset against temperature with fit slope and correlation, a CPU temp row in the Stats table and in the status line. New keys `[source] host_temp` and `[intervals] host`; graph ids `temp`, `temp-freq`, `temp-offset`. Hosts without a temperature reading hide these graphs.
- Fixed blank NTP and peer graphs on the 2h range. Their buckets are now never shorter than `[intervals] ntp`, so a 60 s poll no longer leaves every other 30 s bucket empty.
- Sky plot legend: colour key per constellation in view with used/visible counts, a filled/ring key, and a "used N of M satellites" line.
- New `[web] cursor` option. `hover` (default) keeps the current behaviour; `last` marks the newest point with a dashed line and shows its values under each graph until the pointer moves over the plot.
- Single-page layout keeps the whole header, status line included, on top while scrolling, and the section buttons land below it.
- Docker Compose file `deploy/compose.yaml` and config template `deploy/config.docker.toml`, mounted read-only as `/config.toml`. The Docker docs show both and how to keep custom copies outside the repository.
- Docs on where `samples.db` is saved for each install type, how to back it up while the collector runs, and how to restore it.

## 0.1.0 - 2026-11-24

First version. Needs Python 3.11 or newer and no pip packages. Licensed under Apache 2.0.

- Collector with two sources: `bridge` polls the GPSNTPHomeBridge JSON endpoints over HTTP; `local` reads `chronyc` or `ntpq` and gpsd on the same machine, using monitoring commands only. Both use the bridge's field mapping, so the graphs match whichever source feeds them.
- The collector treats the bridge's zero-satellite record with no timestamp as missing GPS data, and keeps unsynchronised readings (stratum 0 or 16) out of the graphs while still showing them in the status line.
- SQLite store with 7 days of raw samples, 90 days of 5-minute averages and 3 years of hourly averages, all configurable.
- Static web UI using a bundled copy of uPlot 1.6.31: system offset, jitter, frequency and wander, root delay and dispersion, stratum, per-peer offset, delay, jitter and reach, satellites used and visible per constellation, signal strength, DOP and a sky plot.
- ntpviz-style Stats page: percentiles, 90% and 98% ranges, an offset histogram and Allan deviation over 24 hours and 7 days, plus per-peer summaries. It can read chrony `tracking.log` or ntpd `loopstats` for finer data.
- TOML config (`/etc/gnss-ntp-graphs/config.toml`, template in `deploy/config.toml`) with `GNG_<SECTION>_<KEY>` environment overrides. The collector refuses unknown keys and bad values with a message naming the key.
- Page options modelled on graphs1090's `default` file: title and header line, tabs or single-page layout, sections and graphs to show, range buttons, graph height, columns, font size, time zone, ms or µs units, reference lines on the offset graph, fixed y-axis limits per graph, status colour limits and peers to hide.
- Light and dark themes. The config sets the default, and a header button lets each viewer switch.
- Plot colours from the ColorBrewer qualitative schemes, Paired by default. A `colourblind_safe` option limits colours to the sets ColorBrewer rates safe and dashes any further lines.
- Header icons linking to the GitHub repository and the documentation site, and a centred credit line in the footer.
- Deployment through a systemd unit, lighttpd and nginx snippets, `install.sh` for bare metal and a Dockerfile.
- Commit-message hook in `.githooks` (Conventional Commits, short subject and body).
