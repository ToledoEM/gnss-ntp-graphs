FROM python:3.12-slim

# Optional: chronyc for local mode with --network host (reads the host's chronyd)
ARG WITH_CHRONYC=0
RUN if [ "$WITH_CHRONYC" = 1 ]; then \
      apt-get update && apt-get install -y --no-install-recommends chrony \
      && rm -rf /var/lib/apt/lists/*; \
    fi

RUN useradd --system --uid 10001 --home-dir /data gnssgraphs \
    && mkdir -p /data && chown gnssgraphs /data

WORKDIR /app
COPY gnss_ntp_graphs /app/gnss_ntp_graphs

ENV PYTHONUNBUFFERED=1 \
    GNG_SOURCE_TYPE=bridge \
    GNG_SOURCE_BRIDGE_URL=http://bridge/ \
    GNG_PATHS_DB=/data/samples.db \
    GNG_PATHS_WWW=/data/www \
    GNG_SERVER_SERVE=true \
    GNG_SERVER_PORT=8080

USER gnssgraphs
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/data/current.json', timeout=4)"

CMD ["python", "-m", "gnss_ntp_graphs", "run"]
