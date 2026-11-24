#!/bin/bash
# gnss-ntp-graphs bare-metal installer (Debian / Raspberry Pi OS).
#
# Installs the collector to /opt/gnss-ntp-graphs, config to
# /etc/gnss-ntp-graphs/config.toml, data to /var/lib/gnss-ntp-graphs, and a
# systemd service running as the unprivileged user gnssgraphs.
#
# It never changes chrony, ntpd, gpsd or GPSNTPHomeBridge. It only installs
# python3 if missing.
set -euo pipefail

PREFIX=/opt/gnss-ntp-graphs
CONF_DIR=/etc/gnss-ntp-graphs
STATE_DIR=/var/lib/gnss-ntp-graphs
UNIT=/etc/systemd/system/gnss-ntp-graphs.service
LIGHTTPD_CONF=/etc/lighttpd/conf-available/89-gnss-ntp-graphs.conf
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SOURCE=""
BRIDGE_URL="http://127.0.0.1/"
WEB=auto
MODE=install

usage() {
    cat <<EOF
Usage: sudo ./install.sh [options]

  --source bridge|local   Data source (default: local if chronyc/ntpq is
                          present, else bridge)
  --bridge-url URL        Bridge base URL for --source bridge
                          (default: $BRIDGE_URL)
  --web lighttpd|builtin|none
                          lighttpd: add /graphs/ alias to lighttpd
                          builtin:  serve on port 8080 from the collector
                          none:     serve $STATE_DIR/www yourself
                          (default: lighttpd if installed, else builtin)
  --uninstall             Remove service, code and config (keeps data
                          unless --purge)
  --purge                 With --uninstall, also delete $STATE_DIR
  -h, --help
EOF
}

PURGE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --source) SOURCE="$2"; shift 2 ;;
        --bridge-url) BRIDGE_URL="$2"; shift 2 ;;
        --web) WEB="$2"; shift 2 ;;
        --uninstall) MODE=uninstall; shift ;;
        --purge) PURGE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage; exit 2 ;;
    esac
done

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 1; }

if [ "$MODE" = uninstall ]; then
    systemctl disable --now gnss-ntp-graphs.service 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    if [ -f "$LIGHTTPD_CONF" ]; then
        lighty-disable-mod gnss-ntp-graphs 2>/dev/null || true
        rm -f "$LIGHTTPD_CONF"
        systemctl reload lighttpd 2>/dev/null || true
    fi
    rm -rf "$PREFIX" "$CONF_DIR"
    [ "$PURGE" = 1 ] && rm -rf "$STATE_DIR"
    echo "removed gnss-ntp-graphs$([ "$PURGE" = 1 ] && echo " and its data")"
    exit 0
fi

if ! command -v python3 >/dev/null; then
    apt-get update && apt-get install -y python3
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || { echo "python 3.11 or newer required" >&2; exit 1; }

if [ -z "$SOURCE" ]; then
    if command -v chronyc >/dev/null || command -v ntpq >/dev/null; then SOURCE=local; else SOURCE=bridge; fi
fi
case "$SOURCE" in bridge|local) ;; *) echo "--source must be bridge or local" >&2; exit 2 ;; esac

if [ "$WEB" = auto ]; then
    if command -v lighttpd >/dev/null; then WEB=lighttpd; else WEB=builtin; fi
fi
case "$WEB" in lighttpd|builtin|none) ;; *) echo "--web must be lighttpd, builtin or none" >&2; exit 2 ;; esac

id gnssgraphs >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin gnssgraphs

install -d "$PREFIX" "$CONF_DIR"
rm -rf "$PREFIX/gnss_ntp_graphs"
cp -r "$SRC/gnss_ntp_graphs" "$PREFIX/"
find "$PREFIX" -name __pycache__ -prune -exec rm -rf {} +

if [ ! -f "$CONF_DIR/config.toml" ]; then
    serve=false; [ "$WEB" = builtin ] && serve=true
    sed -e "s|^type = .*|type = \"$SOURCE\"|" \
        -e "s|^bridge_url = .*|bridge_url = \"$BRIDGE_URL\"|" \
        -e "s|^serve = .*|serve = $serve|" \
        "$SRC/deploy/config.toml" > "$CONF_DIR/config.toml"
    echo "wrote $CONF_DIR/config.toml (source=$SOURCE)"
else
    echo "kept existing $CONF_DIR/config.toml"
fi

install -m 0644 "$SRC/deploy/gnss-ntp-graphs.service" "$UNIT"
systemctl daemon-reload
systemctl enable gnss-ntp-graphs.service
systemctl restart gnss-ntp-graphs.service

if [ "$WEB" = lighttpd ]; then
    install -m 0644 "$SRC/deploy/lighttpd-gnss-ntp-graphs.conf" "$LIGHTTPD_CONF"
    lighty-enable-mod gnss-ntp-graphs >/dev/null 2>&1 || true
    if lighttpd -tt -f /etc/lighttpd/lighttpd.conf >/dev/null; then
        systemctl reload lighttpd
        echo "graphs: http://$(hostname -I 2>/dev/null | cut -d' ' -f1)/graphs/"
    else
        lighty-disable-mod gnss-ntp-graphs >/dev/null 2>&1 || true
        echo "lighttpd config test failed; alias disabled. Serve $STATE_DIR/www yourself." >&2
    fi
elif [ "$WEB" = builtin ]; then
    echo "graphs: http://$(hostname -I 2>/dev/null | cut -d' ' -f1):8080/"
else
    echo "serve $STATE_DIR/www with your web server (see deploy/nginx-gnss-ntp-graphs.conf)"
fi
