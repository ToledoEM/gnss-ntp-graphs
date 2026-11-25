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
--8<-- "deploy/compose.yaml"
```

`config.docker.toml`:

```toml
--8<-- "deploy/config.docker.toml"
```

The temperature graphs show the time server's CPU temperature, so they only appear when the bridge publishes `cpu_temp.json`. One command on the time server sets that up: see [Publishing the temperature from the bridge](raspberry-pi.md#publishing-the-temperature-from-the-bridge).

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
