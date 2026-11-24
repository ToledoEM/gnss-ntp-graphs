"""SQLite sample store with rollup tiers.

Raw samples are kept for `raw_days` (default 7). They are rolled up into
5-minute averages (kept `days_5m`, default 90) and hourly averages (kept
`days_1h`, default 1095). Queries pick the finest tier that covers the
requested range.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from typing import Any

from .sources.base import CONSTELLATIONS, DOPS, GpsSample, PeerSample, SystemSample

SYSTEM_NUM = [
    "offset",
    "sys_jitter",
    "clk_jitter",
    "frequency",
    "wander",
    "rootdelay",
    "rootdisp",
    "stratum",
]
SYSTEM_TXT = ["refid", "leap"]
PEER_NUM = ["stratum", "poll", "reach", "delay", "offset", "jitter"]
PEER_TXT = ["tally", "refid", "type"]
GPS_NUM = (
    ["total", "used", "avg_ss"]
    + [f"vis_{c}" for c in CONSTELLATIONS]
    + [f"used_{c}" for c in CONSTELLATIONS]
    + DOPS
)

TABLES = {
    # name: (key columns beyond ts, numeric columns, text columns)
    "system": ([], SYSTEM_NUM, SYSTEM_TXT),
    "peers": (["remote"], PEER_NUM, PEER_TXT),
    "gps": ([], GPS_NUM, []),
}
TIERS = [("", 0), ("_5m", 300), ("_1h", 3600)]


def _ddl(name: str) -> list[str]:
    keys, num, txt = TABLES[name]
    out = []
    for suffix, _ in TIERS:
        cols = ["ts INTEGER NOT NULL"] + [f"{k} TEXT NOT NULL" for k in keys]
        cols += [f"{c} REAL" for c in num] + [f"{c} TEXT" for c in txt]
        pk = ", ".join(["ts"] + keys)
        out.append(
            f"CREATE TABLE IF NOT EXISTS {name}{suffix} ({', '.join(cols)}, PRIMARY KEY ({pk}))"
        )
    return out


class Store:
    def __init__(self, path: str, raw_days: float = 7, days_5m: float = 90, days_1h: float = 1095):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        for name in TABLES:
            for stmt in _ddl(name):
                self.db.execute(stmt)
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.commit()
        self.retention = {"": raw_days * 86400, "_5m": days_5m * 86400, "_1h": days_1h * 86400}

    def close(self) -> None:
        self.db.close()

    # --- writes -------------------------------------------------------------

    def _insert(self, table: str, rows: Iterable[dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        self.db.executemany(sql, [tuple(r[c] for c in cols) for r in rows])

    def set_meta(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def add_system(self, s: SystemSample) -> None:
        # Unsynchronised (stratum 0 or 16) reports placeholder values such as
        # a 1 s root delay; keep them as latest status but out of the series.
        if s.stratum not in (0, 16):
            self._insert("system", [asdict(s)])
        self.set_meta("system_latest", asdict(s))
        self.db.commit()

    def add_peers(self, peers: Sequence[PeerSample]) -> None:
        self._insert("peers", [asdict(p) for p in peers])
        self.set_meta("peers_latest", [asdict(p) for p in peers])
        self.db.commit()

    def add_gps(self, g: GpsSample) -> None:
        row: dict[str, Any] = {"ts": g.ts, "total": g.total, "used": g.used, "avg_ss": g.avg_ss}
        for c in CONSTELLATIONS:
            row[f"vis_{c}"] = g.visible_by.get(c, 0)
            row[f"used_{c}"] = g.used_by.get(c, 0)
        for d in DOPS:
            row[d] = g.dops.get(d)
        self._insert("gps", [row])
        self.set_meta("gps_latest", asdict(g))
        self.db.commit()

    # --- maintenance --------------------------------------------------------

    def rollup(self, now: int | None = None) -> None:
        """Rebuild rollup buckets touched since the last run, then prune."""
        now = int(now if now is not None else time.time())
        for name, (keys, num, txt) in TABLES.items():
            prev = ""
            for suffix, step in TIERS[1:]:
                mark = f"rollup{suffix}_{name}"
                since = self.get_meta(mark, 0)
                since = (since // step) * step
                aggs = [f"AVG({c})" for c in num] + [f"MAX({c})" for c in txt]
                group = ", ".join(["b"] + keys)
                self.db.execute(
                    f"INSERT OR REPLACE INTO {name}{suffix} (ts, {', '.join(keys + num + txt)}) "
                    f"SELECT b, {', '.join(keys + aggs)} FROM "
                    f"(SELECT (ts / {step}) * {step} AS b, * FROM {name}{prev} WHERE ts >= ?) "
                    f"GROUP BY {group}",
                    (since,),
                )
                self.set_meta(mark, now)
                prev = suffix
            for suffix, _ in TIERS:
                self.db.execute(
                    f"DELETE FROM {name}{suffix} WHERE ts < ?", (now - self.retention[suffix],)
                )
        self.db.commit()

    # --- reads --------------------------------------------------------------

    def _tier(self, start: int, now: int) -> str:
        age = now - start
        if age <= self.retention[""]:
            return ""
        if age <= self.retention["_5m"]:
            return "_5m"
        return "_1h"

    def series(
        self,
        table: str,
        columns: Sequence[str],
        start: int,
        end: int,
        step: int,
        where: tuple[str, Any] | None = None,
        now: int | None = None,
    ) -> dict[str, list[Any]]:
        """Bucketed averages on a regular grid; missing buckets are None."""
        now = int(now if now is not None else time.time())
        tier = self._tier(start, now)
        cond, args = "ts >= ? AND ts < ?", [start, end]
        if where:
            cond += f" AND {where[0]} = ?"
            args.append(where[1])
        aggs = ", ".join(f"AVG({c})" for c in columns)
        rows = self.db.execute(
            f"SELECT (ts / {step}) * {step} AS b, {aggs} FROM {table}{tier} WHERE {cond} GROUP BY b",
            args,
        ).fetchall()
        by_b = {r[0]: r[1:] for r in rows}
        grid = list(range((start // step) * step, end, step))
        out: dict[str, list[Any]] = {"t": grid}
        for i, c in enumerate(columns):
            out[c] = [
                None if by_b.get(b) is None or by_b[b][i] is None else round(by_b[b][i], 6)
                for b in grid
            ]
        return out

    def raw(
        self, table: str, columns: Sequence[str], start: int, where: tuple[str, Any] | None = None
    ) -> list[tuple]:
        cond, args = "ts >= ?", [start]
        if where:
            cond += f" AND {where[0]} = ?"
            args.append(where[1])
        return self.db.execute(
            f"SELECT ts, {', '.join(columns)} FROM {table} WHERE {cond} ORDER BY ts", args
        ).fetchall()

    def peer_names(self, start: int, now: int | None = None) -> list[str]:
        now = int(now if now is not None else time.time())
        tier = self._tier(start, now)
        return [
            r[0]
            for r in self.db.execute(
                f"SELECT DISTINCT remote FROM peers{tier} WHERE ts >= ? ORDER BY remote", (start,)
            )
        ]
