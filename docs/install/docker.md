# Docker

The Dockerfile builds a small image on `python:3.12-slim`. It runs the collector as user `gnssgraphs` (UID 10001), keeps its data in the `/data` volume and serves the page on port 8080 with the built-in web server.

## Bridge source

This is the usual setup: the container polls GPSNTPHomeBridge over HTTP.

```bash
docker build -t gnss-ntp-graphs .
docker run -d --name gnss-ntp-graphs -p 8080:8080 \
  -e GNG_SOURCE_BRIDGE_URL=http://192.168.1.50/ \
  -v gnss-ntp-graphs:/data gnss-ntp-graphs
```

Open `http://<docker-host>:8080/`.

## Docker Compose with a custom config

`deploy/` has a Compose file and a config template. Keep your own copies outside the repository, so a `git pull` never overwrites your settings.

1. Copy `deploy/compose.yaml` and `deploy/config.docker.toml` into a folder of your own, for example `~/gnss-ntp-graphs/`.
2. In `compose.yaml`, set `build.context` to the folder holding this repository (the one with the `Dockerfile`), and `GNG_SOURCE_BRIDGE_URL` to your bridge.
3. Edit `config.docker.toml`. Only the keys you change are needed.
4. Start it with `docker compose up -d`.

After a change to the TOML file, run `docker compose restart`. After pulling a new version of the code, run `docker compose up -d --build`.

The image sets `source.type`, `source.bridge_url`, `paths.db`, `paths.www`, `server.serve` and `server.port` through `GNG_*` environment variables, and these win over the file. Change those six under `environment:` in `compose.yaml`. Every other key goes in the TOML file.

`compose.yaml`:

```yaml
# Docker Compose for gnss-ntp-graphs with a custom TOML config.
# Copy this file and config.docker.toml into one folder, edit the TOML, then:
#   docker compose up -d
# After editing the TOML: docker compose restart
# Set "context" to the folder holding this repository's Dockerfile.

services:
  gnss-ntp-graphs:
    build:
      context: ..
      # Local source only: include chronyc in the image
      # args:
      #   WITH_CHRONYC: "1"
    image: gnss-ntp-graphs
    container_name: gnss-ntp-graphs
    command: ["python", "-m", "gnss_ntp_graphs", "-c", "/config.toml", "run"]
    ports: ["8080:8080"]
    # The image sets these through GNG_* variables, which win over the TOML
    environment:
      GNG_SOURCE_TYPE: bridge  # bridge | local
      GNG_SOURCE_BRIDGE_URL: http://192.168.1.50/
    # Local source only: read chronyd and gpsd on the Docker host.
    # Remove "ports" above when using host networking.
    # network_mode: host
    volumes:
      - gnss-ntp-graphs:/data
      - ./config.docker.toml:/config.toml:ro
    restart: unless-stopped

volumes:
  gnss-ntp-graphs:
```

`config.docker.toml`:

```toml
# gnss-ntp-graphs configuration for Docker Compose (see compose.yaml).
# Only the keys you change are needed; anything left out keeps its default.
# Full list of keys: deploy/config.toml or the Configuration docs.
#
# The image sets source.type, source.bridge_url, paths.db, paths.www,
# server.serve and server.port through GNG_* environment variables, and the
# environment wins over this file. To change one of those, set it under
# "environment:" in compose.yaml instead (e.g. GNG_SOURCE_BRIDGE_URL).

[web]
title = "GNSS NTP"
header = ""
# "tabs" or "single"
layout = "tabs"
# "hover" or "last"
cursor = "hover"
default_range = "24h"
timezone = "local"
offset_unit = "ms"

[intervals]
ntp = 60
gps = 15
export = 60

[retention]
raw_days = 7.0
days_5m = 90.0
days_1h = 1095.0
```

For the local source, uncomment `WITH_CHRONYC` and `network_mode: host`, remove `ports`, and set `GNG_SOURCE_TYPE: local`.

## Local source

To read a chronyd running on the Docker host, build the image with `chronyc` included and give the container the host network:

```bash
docker build --build-arg WITH_CHRONYC=1 -t gnss-ntp-graphs .
docker run -d --name gnss-ntp-graphs --network host \
  -e GNG_SOURCE_TYPE=local \
  -v gnss-ntp-graphs:/data gnss-ntp-graphs
```

With `--network host` the page is on port 8080 of the host and gpsd is reachable at `127.0.0.1:2947`.

## Image defaults

The image sets these environment variables. Override any of them with `-e`, and any other key with `GNG_<SECTION>_<KEY>` (see [Configuration](../configuration/index.md)).

| Variable | Value |
|---|---|
| `GNG_SOURCE_TYPE` | `bridge` |
| `GNG_SOURCE_BRIDGE_URL` | `http://bridge/` |
| `GNG_PATHS_DB` | `/data/samples.db` |
| `GNG_PATHS_WWW` | `/data/www` |
| `GNG_SERVER_SERVE` | `true` |
| `GNG_SERVER_PORT` | `8080` |

To use a TOML file instead, mount it and pass `-c`:

```bash
docker run -d -p 8080:8080 -v gnss-ntp-graphs:/data \
  -v ./config.toml:/config.toml:ro gnss-ntp-graphs \
  python -m gnss_ntp_graphs -c /config.toml run
```

Environment variables still win over the file.

## Data and backups

The history lives in `/data/samples.db` inside the `gnss-ntp-graphs` volume. See [Where data is saved](../configuration/collector.md#where-data-is-saved) for backing it up.

## Health check

The image's `HEALTHCHECK` fetches `http://127.0.0.1:8080/data/current.json` every 60 seconds. `docker ps` shows the container as `healthy` once the collector has written its first export, usually within a minute of starting.
