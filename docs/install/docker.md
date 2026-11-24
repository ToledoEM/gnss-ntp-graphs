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

The same as a Compose service:

```yaml
services:
  gnss-ntp-graphs:
    build: .
    ports: ["8080:8080"]
    environment:
      GNG_SOURCE_BRIDGE_URL: http://192.168.1.50/
      GNG_WEB_TITLE: Garage time server
    volumes: ["gnss-ntp-graphs:/data"]
    restart: unless-stopped
volumes:
  gnss-ntp-graphs:
```

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

## Health check

The image's `HEALTHCHECK` fetches `http://127.0.0.1:8080/data/current.json` every 60 seconds. `docker ps` shows the container as `healthy` once the collector has written its first export, usually within a minute of starting.
