"""TOML config (stdlib tomllib, Python 3.11+).

The file only needs the keys you change; everything else comes from DEFAULTS.
Any scalar or list key can also be set from the environment as
GNG_<SECTION>_<KEY>, e.g. GNG_SOURCE_TYPE=local or GNG_WEB_SECTIONS=ntp,peers.
"""

from __future__ import annotations

import copy
import json
import os
import tomllib
from pathlib import Path
from typing import Any

COLORBREWER = Path(__file__).resolve().parent / "web" / "vendor" / "colorbrewer-qual.json"


def palettes() -> dict[str, dict[str, Any]]:
    """ColorBrewer qualitative schemes: {name: {"classes": {n: [hex]}, "blind": [...]}}."""
    with open(COLORBREWER) as fh:
        return json.load(fh)["schemes"]


def safe_classes(scheme: dict[str, Any]) -> int:
    """Largest class count ColorBrewer marks colourblind safe (blind flag 1), 0 if none."""
    safe = [i + 3 for i, flag in enumerate(scheme["blind"]) if flag == 1]
    return max(safe) if safe else 0


RANGE_NAMES = ["2h", "8h", "24h", "7d", "30d", "1y"]
SECTIONS = ["ntp", "peers", "gps", "stats"]
GRAPH_IDS = [
    "offset",
    "jitter",
    "freq",
    "root",
    "stratum",
    "peer-offset",
    "peer-delay",
    "peer-jitter",
    "peer-reach",
    "sats",
    "const",
    "ss",
    "dop",
    "sky",
    "hist",
    "adev",
    "temp",
    "temp-freq",
    "temp-offset",
]

DEFAULTS: dict[str, Any] = {
    "source": {
        "type": "bridge",  # bridge | local
        "bridge_url": "http://127.0.0.1/",
        "ntp": "auto",  # auto | chrony | ntpd   (local only)
        "gpsd_host": "127.0.0.1",
        "gpsd_port": 2947,
        "timeout": 10.0,
        "host_temp": True,  # CPU temperature of the collector's host
    },
    "intervals": {  # seconds
        "ntp": 60,
        "gps": 15,
        "host": 60,
        "export": 60,
        "rollup": 300,
        "stats": 900,
    },
    "paths": {
        "db": "/var/lib/gnss-ntp-graphs/samples.db",
        "www": "/var/lib/gnss-ntp-graphs/www",
        "web_src": "",
    },
    "retention": {
        "raw_days": 7.0,
        "days_5m": 90.0,
        "days_1h": 1095.0,
    },
    "logs": {
        "chrony_tracking": "",
        "ntpd_loopstats": "",
    },
    "server": {
        "serve": False,
        "bind": "0.0.0.0",  # noqa: S104 - LAN page server; set bind to narrow it
        "port": 8080,
    },
    "web": {
        "title": "GNSS NTP",
        "header": "",
        "repo_url": "https://github.com/ToledoEM/gnss-ntp-graphs",
        "docs_url": "https://toledoem.github.io/gnss-ntp-graphs/",
        "theme": "auto",  # auto | light | dark
        "palette": "Paired",  # ColorBrewer qualitative scheme
        "colourblind_safe": False,
        "layout": "tabs",  # tabs | single
        "cursor": "hover",  # hover | last
        "sections": list(SECTIONS),
        "hide_graphs": [],
        "ranges": list(RANGE_NAMES),
        "default_range": "24h",
        "graph_height": 220,
        "columns": "auto",  # auto | 1 | 2 | 3
        "font_size": 14,
        "timezone": "local",  # local | UTC | IANA name
        "offset_unit": "ms",  # ms | us
        "offset_lines": [],
        "offset_warn_ms": 1.0,
        "offset_bad_ms": 10.0,
        "stale_warn_s": 120,
        "stale_bad_s": 300,
        "max_peers": 16,
        "hide_peers": [],
    },
    "graphs": {},  # [graphs.<id>] y_min / y_max
}

CHOICES = {
    ("source", "type"): {"bridge", "local"},
    ("source", "ntp"): {"auto", "chrony", "ntpd"},
    ("web", "theme"): {"auto", "light", "dark"},
    ("web", "layout"): {"tabs", "single"},
    ("web", "cursor"): {"hover", "last"},
    ("web", "offset_unit"): {"ms", "us"},
}

ENV_PREFIX = "GNG_"


class ConfigError(ValueError):
    pass


def _coerce(value: Any, default: Any, where: str) -> Any:
    """Check value against the default's type. Ints are accepted for floats."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
    elif isinstance(default, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    elif isinstance(default, int):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif isinstance(default, list):
        if isinstance(value, list):
            return value
    elif isinstance(value, type(default)):
        return value
    raise ConfigError(f"{where}: expected {type(default).__name__}, got {value!r}")


def _from_env(text: str, default: Any, where: str) -> Any:
    if isinstance(default, bool):
        low = text.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"{where}: expected true/false, got {text!r}")
    try:
        if isinstance(default, float):
            return float(text)
        if isinstance(default, int):
            return int(text)
    except ValueError:
        raise ConfigError(f"{where}: expected number, got {text!r}") from None
    if isinstance(default, list):
        items = [s.strip() for s in text.split(",") if s.strip()]
        out = []
        for s in items:
            try:
                out.append(float(s))
            except ValueError:
                out.append(s)
        return out
    return text


def _validate(cfg: dict[str, Any]) -> None:
    for (sec, key), allowed in CHOICES.items():
        if cfg[sec][key] not in allowed:
            raise ConfigError(f"[{sec}] {key}: {cfg[sec][key]!r} not one of {sorted(allowed)}")
    web = cfg["web"]
    schemes = palettes()
    if web["palette"] not in schemes:
        raise ConfigError(f"[web] palette: {web['palette']!r} not one of {sorted(schemes)}")
    if web["colourblind_safe"]:
        safe = sorted(n for n, s in schemes.items() if safe_classes(s))
        if web["palette"] not in safe:
            raise ConfigError(
                f"[web] palette: {web['palette']!r} is not colourblind safe; with "
                f"colourblind_safe = true use one of {safe}"
            )
    if web["columns"] not in ("auto", 1, 2, 3):
        raise ConfigError(f"[web] columns: {web['columns']!r} not one of auto, 1, 2, 3")
    for key, allowed in (
        ("sections", SECTIONS),
        ("ranges", RANGE_NAMES),
        ("hide_graphs", GRAPH_IDS),
    ):
        bad = [v for v in web[key] if v not in allowed]
        if bad:
            raise ConfigError(f"[web] {key}: unknown {bad}, allowed {allowed}")
    if not web["sections"]:
        raise ConfigError("[web] sections: at least one section is needed")
    if not web["ranges"]:
        raise ConfigError("[web] ranges: at least one range is needed")
    if web["default_range"] not in web["ranges"]:
        raise ConfigError(
            f"[web] default_range: {web['default_range']!r} is not in ranges {web['ranges']}"
        )
    if not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in web["offset_lines"]
    ):
        raise ConfigError("[web] offset_lines: numbers only")
    for gid, limits in cfg["graphs"].items():
        if gid not in GRAPH_IDS:
            raise ConfigError(f"[graphs.{gid}]: unknown graph, allowed {GRAPH_IDS}")
        if not isinstance(limits, dict):
            raise ConfigError(f"[graphs.{gid}]: must be a table")
        for k, v in limits.items():
            if (
                k not in ("y_min", "y_max")
                or not isinstance(v, (int, float))
                or isinstance(v, bool)
            ):
                raise ConfigError(f"[graphs.{gid}] {k}: only numeric y_min / y_max allowed")


def load(path: str | None = None) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        with open(path, "rb") as fh:
            try:
                user = tomllib.load(fh)
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"{path}: {e}") from None
        for sec, values in user.items():
            if sec not in cfg:
                raise ConfigError(f"[{sec}]: unknown section, allowed {sorted(cfg)}")
            if not isinstance(values, dict):
                raise ConfigError(f"{sec}: must be a [table]")
            if sec == "graphs":
                cfg["graphs"] = values
                continue
            for key, value in values.items():
                if key not in cfg[sec]:
                    raise ConfigError(f"[{sec}] {key}: unknown key, allowed {sorted(cfg[sec])}")
                if sec == "web" and key == "columns":  # "auto" or an int, checked in _validate
                    cfg[sec][key] = value
                else:
                    cfg[sec][key] = _coerce(value, DEFAULTS[sec][key], f"[{sec}] {key}")
    for sec, opts in DEFAULTS.items():
        if sec == "graphs":
            continue
        for key, default in opts.items():
            env = os.environ.get(f"{ENV_PREFIX}{sec}_{key}".upper())
            if env is not None:
                where = f"{ENV_PREFIX}{sec}_{key}".upper()
                if sec == "web" and key == "columns":
                    cfg[sec][key] = env if env == "auto" else int(env)
                else:
                    cfg[sec][key] = _from_env(env, default, where)
    _validate(cfg)
    return cfg
