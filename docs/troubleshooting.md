# Troubleshooting

Start with the service log. On an `install.sh` setup:

```bash
journalctl -u gnss-ntp-graphs -n 50
```

In Docker, use `docker logs gnss-ntp-graphs`.

## The service does not start

The log shows `config error:` followed by the key at fault. Fix the key in `/etc/gnss-ntp-graphs/config.toml` and restart. [Validation](configuration/index.md#validation) lists what is checked.

`python 3.11 or newer required` from `install.sh` means the system Python is too old. Raspberry Pi OS Bookworm and Debian 12 have 3.11.

## The page says "No data yet"

The page could not load `data/current.json`.

- `current.json: 404` right after install: the collector has not written its first export yet. Wait a few seconds and reload.
- 404 that does not go away: the web server is serving a different folder. Check the alias points at `/var/lib/gnss-ntp-graphs/www/` and that `[paths] www` matches.
- The page loads but nothing else does: open the browser's developer tools and check the requests to `data/`.

## Graphs say "No data in this range"

No samples fall in the selected range for that graph. Check the log for source warnings:

- `bridge http://.../ntpq_crv.json: ...`: the bridge URL is wrong or the bridge is down. Try the URL with `curl`.
- `chronyc -n -c tracking: ...` or `ntpq -c rv: ...`: the daemon command failed. Run it by hand as the `gnssgraphs` user.
- `gpsd 127.0.0.1:2947: ...`: gpsd is not listening at that address. Check `systemctl status gpsd` and `[source] gpsd_host`.

The 30-day and 1-year ranges read the rollup tiers, which fill up as the rollup job runs every 5 minutes. A fresh install shows little there for a while.

## Gaps in the graphs

A gap means no sample in those buckets. Common causes:

- The collector was stopped, or the host was down.
- The daemon was unsynchronised (stratum 0 or 16). The collector keeps those readings out of the NTP graphs on purpose.
- gpsd returned no satellites, or the bridge reported a GPS failure. The collector stores no GPS sample then.

## "updated" turns amber or red

The age of `current.json` is past `stale_warn_s` or `stale_bad_s`. Either the collector stopped writing (check the log) or the viewing device's clock is wrong. The browser works out the age.

## Offset is around ±1.6 s in Docker

When chronyd runs inside a container without permission to set the clock (`chronyd -x`), it measures the container host's clock against its sources but cannot correct it. Large offsets are expected in that setup. Run the collector against the real time server instead.

## NMEA squashes the peer graphs

The NMEA refclock's offset is often around 100 ms, far above PPS and network servers, so the other lines sit flat at zero. Add it to `[web] hide_peers`, for example `hide_peers = ["NMEA"]`, or open a shorter range and zoom with the mouse.

## The Stats tab says "polled samples" after setting a log

The collector falls back to polled samples when the log path is empty, the file cannot be read, or the window holds 10 rows or fewer. Check that `gnssgraphs` can read the file and that the daemon writes to it (`tail` the file after a few minutes). Compressed rotated files are skipped.

## colourblind_safe refuses my palette

With `colourblind_safe = true` only `Paired`, `Dark2` and `Set2` are accepted. See [Theme and colours](configuration/web-page.md#theme-and-colours).

## lighttpd alias disabled

`install.sh` printed `lighttpd config test failed; alias disabled.` Run `lighttpd -tt -f /etc/lighttpd/lighttpd.conf` to see the error. Another config may already define `/graphs/`, or `mod_alias` may not be loaded. Use `--web builtin` or `--web none` as a workaround.
