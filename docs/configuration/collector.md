# Collector settings

These sections control what the collector reads, how often, and where it keeps the results. The values shown are the defaults.

## source

```toml
[source]
type = "bridge"
bridge_url = "http://127.0.0.1/"
ntp = "auto"
gpsd_host = "127.0.0.1"
gpsd_port = 2947
timeout = 10.0
host_temp = true
```

| Key | Values | Meaning |
|---|---|---|
| `type` | `bridge`, `local` | Read GPSNTPHomeBridge's JSON over HTTP, or read the daemons on this machine. See [Choosing a source](../install/index.md#choosing-a-source) |
| `bridge_url` | URL | Base URL of the bridge's web root. The collector appends `ntpq_crv.json`, `ntpq_pn.json`, `gps.json` and, if present, `cpu_temp.json` |
| `ntp` | `auto`, `chrony`, `ntpd` | `local` only. `auto` uses chrony when `chronyc -n -c tracking` answers, otherwise ntpd |
| `gpsd_host`, `gpsd_port` | host, port | `local` only. Where gpsd listens |
| `timeout` | seconds | Limit for each HTTP request, command or gpsd read |
| `host_temp` | `true`, `false` | Record the time server's CPU temperature. `bridge` reads the bridge's `cpu_temp.json` only, which [`gnss-ntp-cpu-temp`](../install/raspberry-pi.md#publishing-the-temperature-from-the-bridge) publishes on the time server. `local` reads `vcgencmd measure_temp`, else the CPU thermal zone picked by type. No reading means no temperature graphs. See [CPU temperature](../install/raspberry-pi.md#cpu-temperature) |

With `local` and chrony, each NTP poll runs `chronyc -n -c tracking`, `-c sources`, `-c sourcestats` and `chronyc -n ntpdata`. With ntpd it runs `ntpq -c rv` and `ntpq -pn`. Each GPS poll connects to gpsd, sends `?WATCH`, waits for the first `SKY` report that lists satellites and disconnects.

## intervals

```toml
[intervals]
ntp = 60
gps = 15
host = 60
export = 60
rollup = 300
stats = 900
```

All values are in seconds.

| Key | Job |
|---|---|
| `ntp` | Poll the system and peer readings |
| `gps` | Poll the satellite view and DOP |
| `host` | Read the CPU temperature |
| `export` | Write `current.json` and the `range_*.json` files (graphs1090 `DRAW_INTERVAL`) |
| `rollup` | Average raw samples into the 5-minute and hourly tiers, and prune old rows |
| `stats` | Recompute `stats.json` for the Stats tab |

The bridge refreshes its NTP files every 60 seconds and its GPS file every 15, so polling faster than that with `bridge` only stores duplicates. Ranges longer than 2 hours are written once per bucket at most (every 20 minutes for 7 days, every 6 hours for 1 year), so a short `export` interval stays cheap. [How it works](../reference/architecture.md#timers) shows the schedule.

## paths

```toml
[paths]
db = "/var/lib/gnss-ntp-graphs/samples.db"
www = "/var/lib/gnss-ntp-graphs/www"
web_src = ""
```

| Key | Meaning |
|---|---|
| `db` | SQLite database. The parent folder is created if missing |
| `www` | Web root. The collector copies the page here at start and writes `data/` below it |
| `web_src` | Folder to copy the page from instead of the bundled one. Leave empty unless you maintain a modified page |

### Where data is saved

All history is in one SQLite file, `samples.db`, at the `db` path:

| Install | Database |
|---|---|
| Raspberry Pi or Debian (`install.sh`) | `/var/lib/gnss-ntp-graphs/samples.db` |
| Docker | `/data/samples.db` in the `gnss-ntp-graphs` volume. `docker volume inspect gnss-ntp-graphs` shows its folder on the host |
| Development run | Whatever `GNG_PATHS_DB` points to |

The database runs in WAL mode, so `samples.db-wal` and `samples.db-shm` sit next to it while the collector runs. The `www/` folder holds only the page and JSON files the collector rewrites, so it needs no backup.

### Backing up

A plain file copy of a running database can catch it halfway through a write. Use SQLite's backup instead, which is safe while the collector runs:

```bash
sqlite3 /var/lib/gnss-ntp-graphs/samples.db ".backup '/home/pi/samples-$(date +%F).db'"
```

Without the `sqlite3` tool, Python does the same:

```bash
python3 -c "import sqlite3; sqlite3.connect('/var/lib/gnss-ntp-graphs/samples.db').backup(sqlite3.connect('/home/pi/samples-backup.db'))"
```

With Docker, run the backup inside the container and copy the result out:

```bash
docker exec gnss-ntp-graphs python -c "import sqlite3; sqlite3.connect('/data/samples.db').backup(sqlite3.connect('/data/samples-backup.db'))"
docker cp gnss-ntp-graphs:/data/samples-backup.db .
```

The backup is a single self-contained file, with no `-wal` or `-shm` files to copy.

### Restoring

1. Stop the collector: `sudo systemctl stop gnss-ntp-graphs`, or `docker compose stop`.
2. Replace `samples.db` with the backup and delete any `samples.db-wal` and `samples.db-shm` next to it.
3. Set the file's owner to the collector's user: `sudo chown gnssgraphs: /var/lib/gnss-ntp-graphs/samples.db`. In Docker the user is UID 10001.
4. Start the collector again.

## retention

```toml
[retention]
raw_days = 7.0
days_5m = 90.0
days_1h = 1095.0
```

| Key | Tier |
|---|---|
| `raw_days` | Every polled sample. Also the window the Stats tab can look back over |
| `days_5m` | 5-minute averages |
| `days_1h` | Hourly averages. 1095 days is three years |

A graph range reads the finest tier that still covers its start. With the defaults, ranges up to 7 days use raw samples, the 30-day range uses 5-minute averages and the 1-year range uses hourly averages. Keep `raw_days` at 7 or more, because the 7-day statistics window reads raw samples.

## server

```toml
[server]
serve = false
bind = "0.0.0.0"
port = 8080
```

`serve = true` starts the built-in static web server on `bind:port`. `install.sh` sets it when lighttpd is missing, and the Docker image always sets it. See [Web server](../install/web-server.md#built-in-server).
