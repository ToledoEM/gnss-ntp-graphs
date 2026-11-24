"""CLI: python -m gnss_ntp_graphs [-c config.toml] {run,once}"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__, config
from .collector import Collector


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gnss-ntp-graphs", description=__doc__)
    ap.add_argument("-c", "--config", help="TOML file (default: built-in defaults + GNG_* env)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "once"],
        help="run: collect forever (default); once: one poll + full export, then exit",
    )
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = config.load(args.config)
    except (config.ConfigError, OSError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    c = Collector(cfg)
    if args.command == "once":
        c.once()
    else:
        c.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
