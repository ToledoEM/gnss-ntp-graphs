# Data files

The collector writes four kinds of JSON file to `www/data/`. They are plain files, so you can fetch them with `curl` or feed them into other tools. The collector writes each file to a temporary name first and renames it into place, so a reader never sees a half-written file.

Units match the rest of the page: offsets, jitter, delay and dispersion in ms, frequency and wander in ppm, signal in dB-Hz.

## config.json

Written once at start. It holds the resolved `[web]` settings, the `[graphs]` y-axis limits and the colours of the chosen palette.

```json
{
  "web": {"title": "GNSS NTP", "theme": "auto", "ranges": ["2h", "8h", "24h", "7d", "30d", "1y"], "...": "..."},
  "graphs": {"offset": {"y_min": -0.05, "y_max": 0.05}},
  "palette": {"classes": {"3": ["#a6cee3", "#1f78b4", "#b2df8a"], "...": []}, "safe": 4}
}
```

`palette.safe` is the largest colour count ColorBrewer rates colourblind safe for the scheme (0 if none).

## current.json

Written every `[intervals] export` seconds. The status line, the peer table and the sky plot read it.

```json
{
  "generated": 1795535355,
  "version": "0.1.0",
  "source": "bridge",
  "constellations": ["gps", "galileo", "glonass", "beidou", "qzss", "sbas", "navic"],
  "system": {"ts": 1795535355, "offset": -0.004259, "sys_jitter": 0.004362, "clk_jitter": 0.002861,
             "frequency": -4.3421, "wander": 0.005, "rootdelay": 0.0, "rootdisp": 0.013174,
             "stratum": 1, "refid": "PPS", "leap": "Normal"},
  "peers": [{"ts": 1795535355, "remote": "PPS(0)", "tally": "*", "refid": ".PPS.", "stratum": 0,
             "type": "l", "poll": 16.0, "reach": 255, "delay": 0.0, "offset": -0.002433, "jitter": 0.002}],
  "gps": {"ts": 1795535341, "total": 16, "used": 13, "avg_ss": 40.22,
          "visible_by": {"gps": 6, "galileo": 3, "glonass": 3, "beidou": 2, "qzss": 1, "sbas": 1, "navic": 0},
          "used_by": {"gps": 5, "galileo": 2, "glonass": 3, "beidou": 2, "qzss": 0, "sbas": 1, "navic": 0},
          "dops": {"hdop": 0.67, "vdop": 0.91, "pdop": 1.08, "gdop": 1.25, "tdop": 0.58},
          "satellites": [{"PRN": 1, "gnssid": 0, "svid": 1, "el": 83.4, "az": 274.3, "ss": 50.8, "used": true}]},
  "host": {"ts": 1795535340, "cpu_temp": 48.3}
}
```

`generated` is a Unix timestamp. `reach` is the decimal value of the reach register (255 is octal 377). `system`, `peers`, `gps` and `host` are the latest readings (`host` is `null` when no CPU temperature is recorded), even when the system reading is unsynchronised and therefore missing from the graphs.

## range_&lt;name&gt;.json

One file per entry in `[web] ranges`: `range_2h.json`, `range_8h.json`, `range_24h.json`, `range_7d.json`, `range_30d.json`, `range_1y.json`.

```json
{
  "name": "24h", "start": 1795874414, "end": 1795960980, "step": 180, "generated": 1795960814,
  "system": {"t": [1795874400, 1795874580], "offset": [0.0012, null], "sys_jitter": [], "...": []},
  "gps": {"t": [], "total": [], "used": [], "avg_ss": [], "vis_gps": [], "used_gps": [], "hdop": [], "...": []},
  "host": {"t": [1795874400, 1795874580], "cpu_temp": [48.1, 48.3]},
  "peers": {"PPS(0)": {"t": [], "offset": [], "delay": [], "jitter": [], "reach": []}}
}
```

Every array lines up with its `t` array, one value per bucket of `step` seconds. A bucket without samples holds `null`.

| Block | Series |
|---|---|
| `system` | `offset`, `sys_jitter`, `clk_jitter`, `frequency`, `wander`, `rootdelay`, `rootdisp`, `stratum` |
| `gps` | `total`, `used`, `avg_ss`, `vis_<constellation>`, `used_<constellation>`, `hdop`, `vdop`, `pdop`, `gdop`, `tdop` |
| `host` | `cpu_temp` (°C), on the same buckets as `system` |
| `peers.<remote>` | `offset`, `delay`, `jitter`, `reach` |

`peers` holds at most `max_peers` entries and leaves out `hide_peers`.

## stats.json

Written every `[intervals] stats` seconds.

```json
{
  "generated": 1795960814,
  "windows": {
    "24h": {
      "origin": "polled", "tau0": 60,
      "offset": {"n": 1324, "min": -0.02, "max": 0.02, "mean": 0.0001, "stddev": 0.0056,
                 "p1": -0.0143, "p5": -0.0099, "p50": 0.0003, "p95": 0.0091, "p99": 0.0121,
                 "range90": 0.019, "range98": 0.0263},
      "offset_hist": {"x": [], "count": [], "width": 0.0005},
      "frequency": {}, "sys_jitter": {}, "rootdelay": {}, "rootdisp": {},
      "adev": {"tau": [60, 120], "adev": [3.1e-8, 2.2e-8]},
      "cpu_temp": {},
      "thermal": {"step": 300, "temp": [48.1], "frequency": [-4.31], "offset": [0.0002],
                  "fit_frequency": {"slope": 0.021, "intercept": -5.32, "r": 0.93, "n": 288},
                  "fit_offset": {"slope": 0.0001, "intercept": -0.004, "r": 0.12, "n": 288}},
      "gps": {"used": {}, "avg_ss": {}, "tdop": {}, "hdop": {}},
      "peers": {"192.168.1.10": {"offset": {}, "delay": {}, "jitter": {}, "reach_full_pct": 93.9}}
    },
    "7d": {}
  }
}
```

`origin` is `polled`, `chrony_tracking` or `ntpd_loopstats`. `tau0` is the sample spacing in seconds. `adev.tau` is in seconds and `adev.adev` is a dimensionless fraction. Each summary object has the same keys as `offset`. A summary is `null` when the window has no samples.

`thermal` pairs the CPU temperature with the average frequency (ppm) and offset (ms) per bucket of `step` seconds (300 for 24h, 1800 for 7d). The three arrays line up. `fit_*` is the least-squares line `y = slope * temp + intercept` with Pearson `r` and pair count `n`, or `null` with fewer than 3 pairs. `thermal` is `null` when the window has no temperature readings.
