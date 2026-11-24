"""Main loop: poll the source, store samples, export JSON on schedule."""

from __future__ import annotations

import functools
import http.server
import logging
import signal
import threading
import time
from pathlib import Path

from .export import Exporter, install_web
from .sources import make_source
from .sources.local import HostTemp
from .store import Store

log = logging.getLogger(__name__)


def serve(www: str, bind: str, port: int) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep journald quiet
            log.debug(fmt, *args)

        def end_headers(self):
            if self.path.startswith("/data/"):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

    httpd = http.server.ThreadingHTTPServer((bind, port), functools.partial(Handler, directory=www))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("serving %s on http://%s:%d/", www, bind, port)
    return httpd


class Collector:
    def __init__(self, cfg):
        self.cfg = cfg
        db = Path(cfg["paths"]["db"])
        db.parent.mkdir(parents=True, exist_ok=True)
        ret = cfg["retention"]
        self.store = Store(
            str(db), raw_days=ret["raw_days"], days_5m=ret["days_5m"], days_1h=ret["days_1h"]
        )
        self.source = make_source(cfg)
        self.source_name = cfg["source"]["type"]
        self.host = HostTemp(cfg["source"]["timeout"]) if cfg["source"]["host_temp"] else None
        self.www = cfg["paths"]["www"]
        self.exporter = Exporter(self.store, self.www, cfg)
        iv = cfg["intervals"]
        self.jobs = [
            (float(iv["ntp"]), self.poll_ntp),
            (float(iv["gps"]), self.poll_gps),
            (float(iv["host"]), self.poll_host),
            (float(iv["export"]), self.export),
            (float(iv["rollup"]), self.store.rollup),
            (float(iv["stats"]), self.exporter.stats),
        ]
        self.stop = threading.Event()

    def poll_ntp(self) -> None:
        s = self.source.system()
        if s is not None:
            self.store.add_system(s)
        p = self.source.peers()
        if p:
            self.store.add_peers(p)

    def poll_gps(self) -> None:
        g = self.source.gps()
        if g is not None:
            self.store.add_gps(g)

    def poll_host(self) -> None:
        if self.host is None:
            return
        h = self.host.read()
        if h is not None:
            self.store.add_host(h)

    def export(self) -> None:
        self.exporter.current(self.source_name)
        self.exporter.ranges()

    def _install(self) -> None:
        install_web(Path(self.www), self.cfg["paths"]["web_src"] or None)
        self.exporter.web_config()

    def once(self) -> None:
        self._install()
        self.poll_ntp()
        self.poll_gps()
        self.poll_host()
        self.store.rollup()
        self.exporter.current(self.source_name)
        self.exporter.ranges(force=True)
        self.exporter.stats()

    def run(self) -> None:
        self._install()
        srv = self.cfg["server"]
        if srv["serve"]:
            serve(self.www, srv["bind"], srv["port"])
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.stop.set())
        due = [0.0] * len(self.jobs)
        while not self.stop.is_set():
            now = time.monotonic()
            for i, (interval, job) in enumerate(self.jobs):
                if now >= due[i]:
                    due[i] = now + interval
                    try:
                        job()
                    except Exception:  # one failing job must not stop collection
                        log.exception("%s failed", job.__name__)
            self.stop.wait(max(0.5, min(due) - time.monotonic()))
        self.store.close()
