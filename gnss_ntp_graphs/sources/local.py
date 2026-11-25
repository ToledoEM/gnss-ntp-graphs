"""Read the NTP daemon and gpsd on this machine.

Only monitoring commands are run (chronyc tracking/sources/sourcestats/ntpdata,
ntpq rv/peers, vcgencmd measure_temp). Nothing is written to the daemons, to gpsd, or to the bridge's
files. gpsd accepts many clients, so this runs alongside the bridge.

Field mapping matches the bridge's ntp_service_chronyd.sh, so graphs look the
same whichever source feeds them.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import (
    GpsSample,
    HostSample,
    PeerSample,
    SystemSample,
    gps_from_sky,
    peers_from_pn,
    system_from_crv,
)

log = logging.getLogger(__name__)

TALLY_CODES = " x.-+#*o"


def _ms(seconds: float) -> float:
    return round(seconds * 1e9) / 1e6


def _run(cmd: list[str], timeout: float) -> str | None:
    try:
        # Fixed argv lists of monitoring commands, no shell
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)  # noqa: S603
        return out.stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("%s: %s", " ".join(cmd), e)
        return None


def _rows(text: str | None) -> list[list[str]]:
    return [line.split(",") for line in (text or "").splitlines() if line.strip()]


# --- chrony -----------------------------------------------------------------


def chrony_stddevs(sourcestats: str | None) -> dict[str, float]:
    out = {}
    for r in _rows(sourcestats):
        if len(r) >= 8:
            with contextlib.suppress(ValueError):
                out[r[0]] = float(r[7])
    return out


def chrony_crv(tracking: str, sourcestats: str | None) -> dict[str, Any]:
    """chronyc -c tracking -> ntpq_crv.json shape."""
    rows = _rows(tracking)
    if not rows or len(rows[0]) < 14:
        return {"error": "unexpected chronyc tracking output"}
    r = rows[0]
    sd = chrony_stddevs(sourcestats)
    return {
        "refid": r[1],
        "stratum": int(r[2]),
        "offset": _ms(-float(r[5])),
        "sys_jitter": _ms(float(r[6])),
        "clk_jitter": _ms(sd[r[1]]) if r[1] in sd else None,
        "frequency": float(r[7]),
        "clk_wander": float(r[9]),
        "rootdelay": _ms(float(r[10])),
        "rootdisp": _ms(float(r[11])),
        "leap_status": r[13],
    }


def _refid(val: str) -> str:
    """'47505300 (GPS)' -> 'GPS'; '8B8F051E ()' -> '139.143.5.30'."""
    hexid = val.split()[0].upper() if val else ""
    name = val[val.find("(") + 1 : val.rfind(")")] if "(" in val else ""
    if not name and len(hexid) == 8 and hexid != "00000000":
        with contextlib.suppress(ValueError):
            name = ".".join(str(int(hexid[i : i + 2], 16)) for i in range(0, 8, 2))
    return name


def chrony_ntpdata(text: str | None) -> dict[str, dict[str, Any]]:
    """chronyc -n ntpdata -> {address: {"refid": str, "delay": seconds}}."""
    out: dict[str, dict[str, Any]] = {}
    addr = None
    for line in (text or "").splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "Remote address":
            addr = val.split()[0] if val else None
            if addr:
                out[addr] = {"refid": "", "delay": 0.0}
        elif key == "Reference ID" and addr:
            out[addr]["refid"] = _refid(val)
        elif key == "Peer delay" and addr:
            with contextlib.suppress(ValueError, IndexError):
                out[addr]["delay"] = float(val.split()[0])
    return out


def chrony_pn(sources: str, sourcestats: str | None, ntpdata: str | None) -> list[dict[str, Any]]:
    """chronyc -c sources -> ntpq_pn.json shape."""
    sd = chrony_stddevs(sourcestats)
    nd = chrony_ntpdata(ntpdata)
    tally_map = {"*": "*", "+": "+", "-": "-", "x": "x", "~": "-"}
    type_map = {"^": "u", "=": "s", "#": "l"}
    out = []
    for r in _rows(sources):
        if len(r) < 10:
            continue
        try:
            reach = int(r[5], 8)
            st = int(r[3])
            peer = nd.get(r[2])
            if r[0] == "#":
                refid = f".{r[2]}."
            elif peer is None:
                refid = ""
            elif st <= 1:  # same as ntpq: stratum-1 refids are .GPS. style
                refid = f".{peer['refid']}."
            else:
                refid = peer["refid"]
            out.append(
                {
                    "remote": r[2],
                    "tally": tally_map.get(r[1], ""),
                    "refid": refid,
                    "st": st,
                    "t": type_map.get(r[0], ""),
                    "poll": 2 ** int(r[4]),
                    "reach": reach,
                    "delay": _ms(peer["delay"] if peer else 0.0),
                    "offset": _ms(-float(r[7])),
                    "jitter": _ms(sd.get(r[2], 0.0)),
                }
            )
        except ValueError:
            continue
    return out


# --- ntpd -------------------------------------------------------------------


def ntpq_rv(text: str) -> dict[str, Any]:
    """ntpq -c rv -> dict. Quoted values may hold commas and spaces."""
    tokens, cur, quoted = [], "", False
    for ch in text:
        if ch == '"':
            quoted = not quoted
            cur += ch
        elif not quoted and (ch == "," or ch.isspace()):
            if cur.strip():
                tokens.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        tokens.append(cur.strip())
    result: dict[str, Any] = {}
    for tok in tokens:
        key, sep, val = tok.partition("=")
        if sep and key.strip():
            result[key.strip()] = val.strip().strip('"')
    if "leap" in result and "leap_status" not in result:
        result["leap_status"] = {
            "00": "Normal",
            "01": "Insert second",
            "10": "Delete second",
            "11": "Not synchronised",
        }.get(result["leap"], result["leap"])
    return result


def ntpq_pn(text: str) -> list[dict[str, Any]]:
    """ntpq -pn -> ntpq_pn.json shape."""
    out = []
    for line in text.splitlines()[2:]:
        p = line.split()
        if len(p) < 10:
            continue
        remote, tally = p[0], ""
        if len(remote) > 1 and remote[0] in TALLY_CODES:
            tally, remote = remote[0], remote[1:]
        try:
            reach = int(p[6], 8)
        except ValueError:
            reach = 0
        out.append(
            {
                "remote": remote,
                "tally": tally,
                "refid": p[1],
                "st": p[2],
                "t": p[3],
                "poll": p[5],
                "reach": reach,
                "delay": p[7],
                "offset": p[8],
                "jitter": p[9],
            }
        )
    return out


# --- gpsd -------------------------------------------------------------------


def read_gpsd_sky(host: str, port: int, timeout: float) -> dict[str, Any] | None:
    """Return the first SKY report that lists satellites, or None."""
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.sendall(b'?WATCH={"enable":true,"json":true}\n')
            buf = b""
            while time.monotonic() < deadline:
                s.settimeout(max(0.1, deadline - time.monotonic()))
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("class") == "SKY" and msg.get("satellites"):
                        return msg
    except OSError as e:
        log.warning("gpsd %s:%s: %s", host, port, e)
    return None


# --- host -------------------------------------------------------------------

THERMAL_ROOT = Path("/sys/class/thermal")
# Thermal zone types that measure the CPU, in order of preference. Others,
# such as ACPI's acpitz, often report a fixed placeholder (25 or 27.8 °C).
CPU_ZONE_TYPES = (
    "cpu-thermal",
    "cpu_thermal",
    "soc_thermal",
    "x86_pkg_temp",
    "coretemp",
    "k10temp",
)
_TEMP_RE = re.compile(r"temp=(-?\d+(?:\.\d+)?)'C")


def vcgencmd_temp(text: str | None) -> float | None:
    """vcgencmd measure_temp -> °C. "temp=48.3'C" -> 48.3."""
    m = _TEMP_RE.search(text or "")
    return float(m.group(1)) if m else None


def thermal_zone_temp(text: str | None) -> float | None:
    """/sys/class/thermal/.../temp holds millidegrees C."""
    try:
        return round(int((text or "").strip()) / 1000.0, 3)
    except ValueError:
        return None


def cpu_zone(root: Path = THERMAL_ROOT) -> Path | None:
    """temp file of the preferred CPU thermal zone under root, or None."""
    found: dict[str, Path] = {}
    for zone in sorted(root.glob("thermal_zone*")):
        with contextlib.suppress(OSError):
            kind = (zone / "type").read_text().strip()
            found.setdefault(kind, zone / "temp")
    return next((found[k] for k in CPU_ZONE_TYPES if k in found), None)


class HostTemp:
    """CPU temperature of the machine the collector runs on.

    Tries `vcgencmd measure_temp` (Raspberry Pi), then the CPU thermal zone
    picked by type. Machines with neither return None and log it once.
    """

    def __init__(self, timeout: float = 10.0, root: Path = THERMAL_ROOT):
        self.timeout = timeout
        self.root = root
        self.missing_logged = False

    def read(self) -> HostSample | None:
        ts = int(time.time())
        temp = None
        if shutil.which("vcgencmd"):
            temp = vcgencmd_temp(_run(["vcgencmd", "measure_temp"], self.timeout))
        if temp is None:
            zone = cpu_zone(self.root)
            if zone is not None:
                with contextlib.suppress(OSError):
                    temp = thermal_zone_temp(zone.read_text())
        if temp is None:
            if not self.missing_logged:
                log.info(
                    "no CPU temperature on this host (no vcgencmd, no CPU zone in %s)", self.root
                )
                self.missing_logged = True
            return None
        return HostSample(ts=ts, cpu_temp=temp)


class LocalSource:
    def __init__(
        self,
        ntp: str = "auto",
        gpsd_host: str = "127.0.0.1",
        gpsd_port: int = 2947,
        timeout: float = 10.0,
    ):
        self.ntp = ntp
        self.gpsd_host = gpsd_host
        self.gpsd_port = gpsd_port
        self.timeout = timeout
        self.host_temp = HostTemp(timeout)

    def host(self) -> HostSample | None:
        return self.host_temp.read()

    def _daemon(self) -> str:
        if self.ntp in ("chrony", "chronyd"):
            return "chrony"
        if self.ntp in ("ntpd", "ntp"):
            return "ntpd"
        if shutil.which("chronyc") and _run(["chronyc", "-n", "-c", "tracking"], self.timeout):
            return "chrony"
        return "ntpd"

    def system(self) -> SystemSample | None:
        ts = int(time.time())
        if self._daemon() == "chrony":
            tracking = _run(["chronyc", "-n", "-c", "tracking"], self.timeout)
            if not tracking:
                return None
            stats = _run(["chronyc", "-n", "-c", "sourcestats"], self.timeout)
            return system_from_crv(ts, chrony_crv(tracking, stats))
        rv = _run(["ntpq", "-c", "rv"], self.timeout)
        return system_from_crv(ts, ntpq_rv(rv)) if rv else None

    def peers(self) -> list[PeerSample] | None:
        ts = int(time.time())
        if self._daemon() == "chrony":
            sources = _run(["chronyc", "-n", "-c", "sources"], self.timeout)
            if not sources:
                return None
            stats = _run(["chronyc", "-n", "-c", "sourcestats"], self.timeout)
            ntpdata = _run(["chronyc", "-n", "ntpdata"], self.timeout)
            return peers_from_pn(ts, chrony_pn(sources, stats, ntpdata))
        pn = _run(["ntpq", "-pn"], self.timeout)
        return peers_from_pn(ts, ntpq_pn(pn)) if pn else None

    def gps(self) -> GpsSample | None:
        sky = read_gpsd_sky(self.gpsd_host, self.gpsd_port, self.timeout)
        if sky is None:
            return None
        return gps_from_sky(int(time.time()), sky.get("satellites"), sky)
