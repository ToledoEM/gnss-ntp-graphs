"""ntpviz-style summary statistics, stdlib only.

Percentile summaries follow ntpviz: 1/5/50/95/99 percentiles, the 90% range
(p95 - p5) and 98% range (p99 - p1), mean and standard deviation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

PCTS = (1, 5, 50, 95, 99)


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile of a pre-sorted list."""
    if not sorted_vals:
        raise ValueError("empty")
    k = (len(sorted_vals) - 1) * p / 100.0
    lo = math.floor(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def summary(values: Sequence[float | None]) -> dict[str, float] | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    out = {f"p{p}": percentile(vals, p) for p in PCTS}
    out.update(
        n=n,
        min=vals[0],
        max=vals[-1],
        mean=mean,
        stddev=sd,
        range90=out["p95"] - out["p5"],
        range98=out["p99"] - out["p1"],
    )
    return {k: round(v, 6) if isinstance(v, float) else v for k, v in out.items()}


def histogram(
    values: Sequence[float | None], bins: int = 50, clip_pct: float = 1.0
) -> dict[str, list[float]] | None:
    """Histogram between the clip_pct and 100-clip_pct percentiles.

    Outliers beyond those bounds are counted in the edge bins, as ntpviz does
    by plotting the central 98%.
    """
    vals = sorted(v for v in values if v is not None)
    if len(vals) < 2:
        return None
    lo, hi = percentile(vals, clip_pct), percentile(vals, 100 - clip_pct)
    if hi <= lo:
        lo, hi = vals[0] - 0.5, vals[-1] + 0.5
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        i = int((v - lo) / width)
        counts[min(max(i, 0), bins - 1)] += 1
    centers = [round(lo + width * (i + 0.5), 9) for i in range(bins)]
    return {"x": centers, "count": counts, "width": width}


def regularise(samples: Sequence[tuple[int, float | None]], tau0: int) -> list[float | None]:
    """Place (ts, value) samples on a grid of tau0 seconds; gaps become None."""
    pts = [(ts, v) for ts, v in samples if v is not None]
    if not pts:
        return []
    t0 = pts[0][0]
    n = (pts[-1][0] - t0) // tau0 + 1
    grid: list[float | None] = [None] * n
    for ts, v in pts:
        grid[min((ts - t0 + tau0 // 2) // tau0, n - 1)] = v
    return grid


def allan_deviation(
    x: Sequence[float | None], tau0: float, max_points: int = 30
) -> dict[str, list[float]]:
    """Overlapping Allan deviation from time-error samples x (seconds).

    x is on a regular tau0 grid. Triples containing a gap are skipped. Returns
    tau values on a roughly log-spaced set of averaging factors.
    """
    n = len(x)
    taus, adevs = [], []
    if n < 3:
        return {"tau": taus, "adev": adevs}
    ms = sorted({max(1, int(round(10 ** (i / 10.0)))) for i in range(0, 200)})
    ms = [m for m in ms if 2 * m < n][:max_points]
    for m in ms:
        acc, cnt = 0.0, 0
        for i in range(n - 2 * m):
            a, b, c = x[i], x[i + m], x[i + 2 * m]
            if a is None or b is None or c is None:
                continue
            d = c - 2 * b + a
            acc += d * d
            cnt += 1
        if cnt < 2:
            continue
        tau = m * tau0
        taus.append(tau)
        adevs.append(math.sqrt(acc / (2.0 * cnt * tau * tau)))
    return {"tau": taus, "adev": adevs}
