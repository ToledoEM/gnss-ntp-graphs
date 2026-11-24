"""Write the static site's JSON files.

www/
  index.html, app.js, ...     copied from web/ at startup
  data/current.json           latest system, peers, GPS snapshot (sky plot)
  data/range_<name>.json      bucketed series for one time range
  data/stats.json             ntpviz-style summaries
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__, config, logs, stats
from .sources.base import CONSTELLATIONS, DOPS
from .store import GPS_NUM, Store

log = logging.getLogger(__name__)

# name, span seconds, bucket seconds
RANGES = [
    ("2h", 2 * 3600, 30),
    ("8h", 8 * 3600, 60),
    ("24h", 86400, 180),
    ("7d", 7 * 86400, 1200),
    ("30d", 30 * 86400, 3600),
    ("1y", 365 * 86400, 6 * 3600),
]
SYSTEM_COLS = ["offset", "sys_jitter", "clk_jitter", "frequency", "wander", "rootdelay", "rootdisp", "stratum"]
PEER_COLS = ["offset", "delay", "jitter", "reach"]
STATS_WINDOWS = [("24h", 86400), ("7d", 7 * 86400)]

WEB_DIR = Path(__file__).resolve().parent / "web"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(data, fh, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, path)


def install_web(www: Path, src: Optional[str] = None) -> None:
    """Copy static files into the web root, leaving data/ alone."""
    src_dir = Path(src) if src else WEB_DIR
    www.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, www, dirs_exist_ok=True)


class Exporter:
    def __init__(self, store: Store, www: str, cfg):
        self.store = store
        self.data = Path(www) / "data"
        self.cfg = cfg
        self.last_range: Dict[str, float] = {}

    def web_config(self) -> None:
        """Publish the [web] and [graphs] settings for the page."""
        web = dict(self.cfg["web"])
        web["ranges"] = [r[0] for r in RANGES if r[0] in web["ranges"]]
        scheme = config.palettes()[web["palette"]]
        palette = {"classes": scheme["classes"], "safe": config.safe_classes(scheme)}
        write_json(self.data / "config.json", {"web": web, "graphs": self.cfg["graphs"], "palette": palette})

    def current(self, source: str, now: Optional[int] = None) -> None:
        now = int(now if now is not None else time.time())
        write_json(
            self.data / "current.json",
            {
                "generated": now,
                "version": __version__,
                "source": source,
                "constellations": CONSTELLATIONS,
                "system": self.store.get_meta("system_latest"),
                "peers": self.store.get_meta("peers_latest", []),
                "gps": self.store.get_meta("gps_latest"),
            },
        )

    def ranges(self, now: Optional[int] = None, force: bool = False) -> None:
        now = int(now if now is not None else time.time())
        web = self.cfg["web"]
        max_peers = web["max_peers"]
        for name, span, step in RANGES:
            if name not in web["ranges"]:
                continue
            # Long ranges change slowly; refresh them once per bucket
            if not force and now - self.last_range.get(name, 0) < step:
                continue
            self.last_range[name] = now
            start = now - span
            end = (now // step + 1) * step
            peers = {}
            for remote in self.store.peer_names(start, now=now):
                if remote in web["hide_peers"]:
                    continue
                s = self.store.series("peers", PEER_COLS, start, end, step, where=("remote", remote), now=now)
                if any(v is not None for v in s["offset"]):
                    peers[remote] = s
            # Keep the peers with the most data
            ranked = sorted(peers, key=lambda r: -sum(v is not None for v in peers[r]["offset"]))[:max_peers]
            write_json(
                self.data / f"range_{name}.json",
                {
                    "name": name,
                    "start": start,
                    "end": end,
                    "step": step,
                    "generated": now,
                    "system": self.store.series("system", SYSTEM_COLS, start, end, step, now=now),
                    "gps": self.store.series("gps", GPS_NUM, start, end, step, now=now),
                    "peers": {r: peers[r] for r in sorted(ranked)},
                },
            )

    def _offset_series(self, start: int):
        """(ts, offset_ms) rows and their spacing, from a stats log if set."""
        for kind in ("chrony_tracking", "ntpd_loopstats"):
            path = self.cfg["logs"][kind]
            if path:
                rows = logs.read_log(kind, path, start)
                if len(rows) > 10:
                    return [(r[0], r[1]) for r in rows], [(r[0], r[2]) for r in rows], kind
        sys_rows = self.store.raw("system", ["offset", "frequency"], start)
        return [(r[0], r[1]) for r in sys_rows], [(r[0], r[2]) for r in sys_rows], "polled"

    def stats(self, now: Optional[int] = None) -> None:
        now = int(now if now is not None else time.time())
        out: Dict[str, Any] = {"generated": now, "windows": {}}
        for name, span in STATS_WINDOWS:
            start = now - span
            off, freq, origin = self._offset_series(start)
            sys_rows = self.store.raw("system", ["sys_jitter", "rootdelay", "rootdisp"], start)
            gps_rows = self.store.raw("gps", ["used", "avg_ss", "tdop", "hdop"], start)
            off_vals = [v for _, v in off]
            # Regular grid for ADEV: median sample spacing, at least 1 s
            gaps = [b[0] - a[0] for a, b in zip(off, off[1:]) if b[0] > a[0]]
            tau0 = max(1, int(statistics.median(gaps))) if gaps else 60
            grid = stats.regularise([(t, None if v is None else v / 1e3) for t, v in off], tau0)
            w = {
                "origin": origin,
                "tau0": tau0,
                "offset": stats.summary(off_vals),
                "offset_hist": stats.histogram(off_vals),
                "frequency": stats.summary([v for _, v in freq]),
                "sys_jitter": stats.summary([r[1] for r in sys_rows]),
                "rootdelay": stats.summary([r[2] for r in sys_rows]),
                "rootdisp": stats.summary([r[3] for r in sys_rows]),
                "adev": stats.allan_deviation(grid, tau0),
                "gps": {
                    "used": stats.summary([g[1] for g in gps_rows]),
                    "avg_ss": stats.summary([g[2] for g in gps_rows]),
                    "tdop": stats.summary([g[3] for g in gps_rows]),
                    "hdop": stats.summary([g[4] for g in gps_rows]),
                },
                "peers": {},
            }
            for remote in self.store.peer_names(start, now=now):
                rows = self.store.raw("peers", ["offset", "delay", "jitter", "reach"], start, where=("remote", remote))
                if not rows:
                    continue
                reach = [r[4] for r in rows if r[4] is not None]
                w["peers"][remote] = {
                    "offset": stats.summary([r[1] for r in rows]),
                    "delay": stats.summary([r[2] for r in rows]),
                    "jitter": stats.summary([r[3] for r in rows]),
                    "reach_full_pct": round(100.0 * sum(1 for x in reach if x == 255) / len(reach), 1) if reach else None,
                }
            out["windows"][name] = w
        write_json(self.data / "stats.json", out)


__all__ = ["Exporter", "install_web", "write_json", "RANGES", "DOPS"]
