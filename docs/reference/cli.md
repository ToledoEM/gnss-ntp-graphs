# Command line

```text
python -m gnss_ntp_graphs [-c CONFIG] [-v] [--version] [run|once]
```

When installed as a package the same command is available as `gnss-ntp-graphs`.

| Argument | Meaning |
|---|---|
| `-c`, `--config FILE` | TOML config file. Without it the collector uses the built-in defaults plus any `GNG_*` environment variables |
| `-v`, `--verbose` | Debug logging, including the built-in web server's requests |
| `--version` | Print the version and exit |
| `run` | Default. Copy the page into the web root, then poll and export until stopped |
| `once` | One poll of NTP and GPS, a rollup, and a full export of every file, then exit |

`run` stops cleanly on `SIGTERM` or `SIGINT` (Ctrl+C).

`once` is handy for checking a config or a source without starting the service:

```bash
python3 -m gnss_ntp_graphs -c /etc/gnss-ntp-graphs/config.toml -v once
ls /var/lib/gnss-ntp-graphs/www/data/
```

Run it as the `gnssgraphs` user (`sudo -u gnssgraphs ...`) on an installed system, so the files it creates keep the right owner.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Normal exit |
| 2 | Config error, or bad arguments. The message names the key, for example `config error: [web] theme: 'blue' not one of ['auto', 'dark', 'light']` |

Problems reading a source are not fatal. The collector logs a warning such as `bridge http://192.168.1.50/gps.json: <error>` or `gpsd 127.0.0.1:2947: <error>`, skips that sample and tries again on the next interval.
