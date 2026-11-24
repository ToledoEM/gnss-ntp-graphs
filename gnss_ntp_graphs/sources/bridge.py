"""Read GPSNTPHomeBridge JSON endpoints over HTTP. Read-only, GET only."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, List, Optional

from .base import GpsSample, PeerSample, SystemSample, gps_from_sky, peers_from_pn, system_from_crv

log = logging.getLogger(__name__)


class BridgeSource:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def _get(self, name: str) -> Any:
        url = self.base_url + name
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.warning("bridge %s: %s", url, e)
            return None

    def system(self) -> Optional[SystemSample]:
        return system_from_crv(int(time.time()), self._get("ntpq_crv.json"))

    def peers(self) -> Optional[List[PeerSample]]:
        return peers_from_pn(int(time.time()), self._get("ntpq_pn.json"))

    def gps(self) -> Optional[GpsSample]:
        data = self._get("gps.json")
        if not isinstance(data, dict) or "error" in data:
            return None
        # The bridge turns a gpsd failure into a zero-satellite record with no
        # timestamp. Treat that as missing data, not as "0 satellites".
        if data.get("timestamp") is None and not data.get("satellites"):
            return None
        return gps_from_sky(int(time.time()), data.get("satellites"), data.get("dop_values") or {})
