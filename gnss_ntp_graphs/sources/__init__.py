"""Data sources. Each source returns normalised samples or None on failure."""

from __future__ import annotations

from .base import GpsSample, PeerSample, SystemSample


def make_source(cfg):
    """Return the source selected by config ([source] type = bridge|local)."""
    src = cfg["source"]
    kind = src["type"]
    if kind == "bridge":
        from .bridge import BridgeSource

        return BridgeSource(src["bridge_url"], timeout=src["timeout"])
    if kind == "local":
        from .local import LocalSource

        return LocalSource(
            ntp=src["ntp"],
            gpsd_host=src["gpsd_host"],
            gpsd_port=src["gpsd_port"],
            timeout=src["timeout"],
        )
    raise ValueError(f"unknown source type: {kind!r} (use bridge or local)")


__all__ = ["GpsSample", "PeerSample", "SystemSample", "make_source"]
