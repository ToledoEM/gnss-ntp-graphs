"""Read GPSNTPHomeBridge JSON endpoints over HTTP. Read-only, GET only."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from .base import (
    GpsSample,
    HostSample,
    PeerSample,
    SystemSample,
    gps_from_sky,
    peers_from_pn,
    system_from_crv,
    to_float,
)

log = logging.getLogger(__name__)

# cpu_temp.json older than this is treated as missing
HOST_MAX_AGE = 300


def _epoch(value: Any) -> float | None:
    """Unix seconds from a number or an ISO 8601 string."""
    num = to_float(value)
    if num is not None:
        return num
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


class BridgeSource:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.missing_logged: set[str] = set()

    def _get(self, name: str, optional: bool = False) -> Any:
        url = self.base_url + name
        try:
            # URL comes from [source] bridge_url in the admin-owned config
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
            self.missing_logged.discard(name)
            return data
        except (urllib.error.URLError, OSError, ValueError) as e:
            if not optional:
                log.warning("bridge %s: %s", url, e)
            elif name not in self.missing_logged:
                log.info("bridge %s: %s (optional file, skipped until it appears)", url, e)
                self.missing_logged.add(name)
            return None

    def system(self) -> SystemSample | None:
        return system_from_crv(int(time.time()), self._get("ntpq_crv.json"))

    def peers(self) -> list[PeerSample] | None:
        return peers_from_pn(int(time.time()), self._get("ntpq_pn.json"))

    def gps(self) -> GpsSample | None:
        data = self._get("gps.json")
        if not isinstance(data, dict) or "error" in data:
            return None
        # The bridge turns a gpsd failure into a zero-satellite record with no
        # timestamp. Treat that as missing data, not as "0 satellites".
        if data.get("timestamp") is None and not data.get("satellites"):
            return None
        return gps_from_sky(int(time.time()), data.get("satellites"), data.get("dop_values") or {})

    def host(self) -> HostSample | None:
        """CPU temperature the bridge publishes in cpu_temp.json, if it does."""
        data = self._get("cpu_temp.json", optional=True)
        if not isinstance(data, dict):
            return None
        temp = to_float(data.get("cpu_temp"))
        if temp is None:
            return None
        now = int(time.time())
        ts = _epoch(data.get("timestamp"))
        if ts is not None and now - ts > HOST_MAX_AGE:
            return None
        return HostSample(ts=now, cpu_temp=temp)
