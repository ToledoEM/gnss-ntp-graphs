"""Read the NTP daemon and gpsd on this machine.

Only monitoring commands are run (chronyc tracking/sources/sourcestats/ntpdata,
ntpq rv/peers). Nothing is written to the daemons, to gpsd, or to the bridge's
files. gpsd accepts many clients, so this runs alongside the bridge.

Field mapping matches the bridge's ntp_service_chronyd.sh, so graphs look the
same whichever source feeds them.
"""

from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

from .base import GpsSample, PeerSample, SystemSample, gps_from_sky, peers_from_pn, system_from_crv

log = logging.getLogger(__name__)

TALLY_CODES = " x.-+#*o"


def _ms(seconds: float) -> float:
    return round(seconds * 1e9) / 1e6


def _run(cmd: List[str], timeout: float) -> Optional[str]:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
        return out.stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("%s: %s", " ".join(cmd), e)
        return None


def _rows(text: Optional[str]) -> List[List[str]]:
    return [line.split(",") for line in (text or "").splitlines() if line.strip()]


# --- chrony -----------------------------------------------------------------


def chrony_stddevs(sourcestats: Optional[str]) -> Dict[str, float]:
    out = {}
    for r in _rows(sourcestats):
        if len(r) >= 8:
            try:
                out[r[0]] = float(r[7])
            except ValueError:
                pass
    return out


def chrony_crv(tracking: str, sourcestats: Optional[str]) -> Dict[str, Any]:
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
        try:
            name = ".".join(str(int(hexid[i : i + 2], 16)) for i in range(0, 8, 2))
        except ValueError:
            pass
    return name


def chrony_ntpdata(text: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """chronyc -n ntpdata -> {address: {"refid": str, "delay": seconds}}."""
    out: Dict[str, Dict[str, Any]] = {}
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
            try:
                out[addr]["delay"] = float(val.split()[0])
            except (ValueError, IndexError):
                pass
    return out


def chrony_pn(sources: str, sourcestats: Optional[str], ntpdata: Optional[str]) -> List[Dict[str, Any]]:
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


def ntpq_rv(text: str) -> Dict[str, Any]:
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
    result: Dict[str, Any] = {}
    for tok in tokens:
        key, sep, val = tok.partition("=")
        if sep and key.strip():
            result[key.strip()] = val.strip().strip('"')
    if "leap" in result and "leap_status" not in result:
        result["leap_status"] = {"00": "Normal", "01": "Insert second", "10": "Delete second", "11": "Not synchronised"}.get(
            result["leap"], result["leap"]
        )
    return result


def ntpq_pn(text: str) -> List[Dict[str, Any]]:
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


def read_gpsd_sky(host: str, port: int, timeout: float) -> Optional[Dict[str, Any]]:
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


class LocalSource:
    def __init__(self, ntp: str = "auto", gpsd_host: str = "127.0.0.1", gpsd_port: int = 2947, timeout: float = 10.0):
        self.ntp = ntp
        self.gpsd_host = gpsd_host
        self.gpsd_port = gpsd_port
        self.timeout = timeout

    def _daemon(self) -> str:
        if self.ntp in ("chrony", "chronyd"):
            return "chrony"
        if self.ntp in ("ntpd", "ntp"):
            return "ntpd"
        if shutil.which("chronyc") and _run(["chronyc", "-n", "-c", "tracking"], self.timeout):
            return "chrony"
        return "ntpd"

    def system(self) -> Optional[SystemSample]:
        ts = int(time.time())
        if self._daemon() == "chrony":
            tracking = _run(["chronyc", "-n", "-c", "tracking"], self.timeout)
            if not tracking:
                return None
            stats = _run(["chronyc", "-n", "-c", "sourcestats"], self.timeout)
            return system_from_crv(ts, chrony_crv(tracking, stats))
        rv = _run(["ntpq", "-c", "rv"], self.timeout)
        return system_from_crv(ts, ntpq_rv(rv)) if rv else None

    def peers(self) -> Optional[List[PeerSample]]:
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

    def gps(self) -> Optional[GpsSample]:
        sky = read_gpsd_sky(self.gpsd_host, self.gpsd_port, self.timeout)
        if sky is None:
            return None
        return gps_from_sky(int(time.time()), sky.get("satellites"), sky)
