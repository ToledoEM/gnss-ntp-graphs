"""Optional readers for daemon statistics logs (local mode only).

These logs give one row per clock update, finer than the 60 s polling, and
cover time before this tool was installed. Neither daemon writes them by
default; see README for the one-line config each needs. This module only
reads them.

Returned offsets are in ms with ntpq sign convention, frequency in ppm.
"""

from __future__ import annotations

import calendar
import glob
import logging
import time

log = logging.getLogger(__name__)

Row = tuple[int, float, float]  # ts, offset_ms, frequency_ppm


def _files(pattern: str) -> list[str]:
    # Rotated files (loopstats.20261124, tracking.log.1) sort before the live one
    found = [p for p in glob.glob(pattern + "*") if not p.endswith((".gz", ".xz", ".bz2"))]
    return sorted(found, key=lambda p: (p == pattern, p))


def parse_chrony_tracking(lines, since: int) -> list[Row]:
    out = []
    for line in lines:
        p = line.split()
        if len(p) < 7 or not p[0][:1].isdigit() or "-" not in p[0]:
            continue
        try:
            ts = calendar.timegm(time.strptime(f"{p[0]} {p[1]}", "%Y-%m-%d %H:%M:%S"))
            if ts < since:
                continue
            # tracking.log offset is local-minus-reference; negate like the bridge
            out.append((ts, round(-float(p[6]) * 1e3, 9), float(p[4])))
        except ValueError:
            continue
    return out


def parse_ntpd_loopstats(lines, since: int) -> list[Row]:
    out = []
    for line in lines:
        p = line.split()
        if len(p) < 4:
            continue
        try:
            ts = int((int(p[0]) - 40587) * 86400 + float(p[1]))
            if ts < since:
                continue
            out.append((ts, round(float(p[2]) * 1e3, 9), float(p[3])))
        except ValueError:
            continue
    return out


def read_log(kind: str, path: str, since: int) -> list[Row]:
    parser = {"chrony_tracking": parse_chrony_tracking, "ntpd_loopstats": parse_ntpd_loopstats}[
        kind
    ]
    rows: list[Row] = []
    for f in _files(path):
        try:
            with open(f, errors="replace") as fh:
                rows.extend(parser(fh, since))
        except OSError as e:
            log.warning("%s: %s", f, e)
    rows.sort()
    return rows
