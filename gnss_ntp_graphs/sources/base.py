"""Normalised sample types shared by every source.

Units follow ntpq: offsets, jitters and delays in milliseconds, frequency and
wander in ppm. Offset sign is source-minus-local, as ntpq prints it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# gnssid -> constellation, per the gpsd JSON protocol (SKY object)
GNSS_IDS = {
    0: "gps",
    1: "sbas",
    2: "galileo",
    3: "beidou",
    4: "imes",
    5: "qzss",
    6: "glonass",
    7: "navic",
}
CONSTELLATIONS = ["gps", "galileo", "glonass", "beidou", "qzss", "sbas", "navic"]
DOPS = ["hdop", "vdop", "pdop", "gdop", "tdop"]


def to_float(value: Any) -> float | None:
    """Coerce bridge values to float. ntpd fields arrive as strings."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    f = to_float(value)
    return None if f is None else int(f)


@dataclass
class SystemSample:
    ts: int
    offset: float | None = None
    sys_jitter: float | None = None
    clk_jitter: float | None = None
    frequency: float | None = None
    wander: float | None = None
    rootdelay: float | None = None
    rootdisp: float | None = None
    stratum: int | None = None
    refid: str | None = None
    leap: str | None = None


@dataclass
class PeerSample:
    ts: int
    remote: str
    tally: str = ""
    refid: str = ""
    stratum: int | None = None
    type: str = ""
    poll: float | None = None
    reach: int | None = None
    delay: float | None = None
    offset: float | None = None
    jitter: float | None = None


@dataclass
class GpsSample:
    ts: int
    total: int = 0
    used: int = 0
    avg_ss: float | None = None
    visible_by: dict[str, int] = field(default_factory=dict)
    used_by: dict[str, int] = field(default_factory=dict)
    dops: dict[str, float | None] = field(default_factory=dict)
    satellites: list[dict[str, Any]] = field(default_factory=list)


def system_from_crv(ts: int, crv: dict[str, Any]) -> SystemSample | None:
    """Build a SystemSample from the ntpq_crv.json shape (bridge or local)."""
    if not isinstance(crv, dict) or "error" in crv:
        return None
    leap = crv.get("leap_status") or crv.get("leap")
    return SystemSample(
        ts=ts,
        offset=to_float(crv.get("offset")),
        sys_jitter=to_float(crv.get("sys_jitter")),
        clk_jitter=to_float(crv.get("clk_jitter")),
        frequency=to_float(crv.get("frequency")),
        wander=to_float(crv.get("clk_wander")),
        rootdelay=to_float(crv.get("rootdelay")),
        rootdisp=to_float(crv.get("rootdisp")),
        stratum=to_int(crv.get("stratum")),
        refid=None if crv.get("refid") is None else str(crv.get("refid")),
        leap=None if leap is None else str(leap),
    )


def peers_from_pn(ts: int, pn: Any) -> list[PeerSample] | None:
    """Build PeerSamples from the ntpq_pn.json shape (bridge or local)."""
    if not isinstance(pn, list):
        return None
    out = []
    for p in pn:
        if not isinstance(p, dict) or not p.get("remote"):
            continue
        out.append(
            PeerSample(
                ts=ts,
                remote=str(p["remote"]),
                tally=str(p.get("tally") or ""),
                refid=str(p.get("refid") or ""),
                stratum=to_int(p.get("st")),
                type=str(p.get("t") or ""),
                poll=to_float(p.get("poll")),
                reach=to_int(p.get("reach")),
                delay=to_float(p.get("delay")),
                offset=to_float(p.get("offset")),
                jitter=to_float(p.get("jitter")),
            )
        )
    return out


def gps_from_sky(ts: int, satellites: Any, dops: dict[str, Any]) -> GpsSample:
    """Build a GpsSample from a gpsd SKY satellite list and DOP values.

    Per-constellation used counts are derived from the list, since the bridge
    only publishes visible counts.
    """
    sats = [s for s in (satellites or []) if isinstance(s, dict)]
    visible_by = {c: 0 for c in CONSTELLATIONS}
    used_by = {c: 0 for c in CONSTELLATIONS}
    ss_used = []
    for s in sats:
        name = GNSS_IDS.get(s.get("gnssid"))
        if name in visible_by:
            visible_by[name] += 1
            if s.get("used"):
                used_by[name] += 1
        if s.get("used") and to_float(s.get("ss")) is not None:
            ss_used.append(float(s["ss"]))
    keep = ("PRN", "gnssid", "svid", "el", "az", "ss", "used")
    return GpsSample(
        ts=ts,
        total=len(sats),
        used=sum(1 for s in sats if s.get("used")),
        avg_ss=round(sum(ss_used) / len(ss_used), 2) if ss_used else None,
        visible_by=visible_by,
        used_by=used_by,
        dops={d: to_float(dops.get(d)) for d in DOPS},
        satellites=[{k: s.get(k) for k in keep} for s in sats],
    )
