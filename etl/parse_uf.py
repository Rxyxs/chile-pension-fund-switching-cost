"""Clean the raw UF series into one value per calendar day.

The raw download has two real defects, both found by checking it rather than
assuming a central-bank mirror is clean:

- **Duplicated days.** 2015-07-11 appears five times. The copies are identical and
  fit their neighbours (~4.02 CLP/day that month), so they are collapsed. If two
  copies of a day ever *disagree*, that is not a duplicate but a conflict, and it
  raises instead of silently picking one.
- **Missing days.** 2015-12-12 and 2015-12-31 are absent. The UF is defined to grow
  at a constant daily geometric rate between the 10th of one month and the 9th of
  the next, so geometric interpolation between the neighbours is not an
  approximation -- it reproduces the value the formula would have published.
  Gaps longer than a few days would no longer be safe to fill that way, so those
  raise too.

And a third one, worse, that a single spot-check could never have caught:

- **The US dollar leaked into the UF series.** On 2014-12-29 and 2014-12-30 the
  "UF" is 608.15 and 607.38 -- the *dólar observado* of those days -- instead of
  24,627.10. Deflating by it made the real fund index jump x40 and back, which
  sent the excess kurtosis of daily returns to ~4,300 and would have wrecked any
  volatility model. The guard is structural, not a hardcoded date: the UF cannot
  move 1% in a day (that would be ~35% monthly inflation; the largest legitimate
  daily move in 2002-2026 is 0.063%, from March 2022's 1.9% CPI). Any day that
  jumps more than that from the last valid value is discarded and refilled by
  interpolation like any other missing day.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "raw" / "uf_daily.json"
OUT_PATH = ROOT / "data" / "processed" / "uf_daily.parquet"

MAX_GAP_DAYS = 3
MAX_DAILY_LOG_MOVE = 0.01


def clean_uf(rows: list[dict]) -> tuple[list[tuple[date, float]], dict]:
    """Return (sorted daily series, report of what was fixed)."""
    by_day: dict[date, float] = {}
    duplicates = 0
    for r in rows:
        d = date.fromisoformat(r["fecha"])
        v = float(r["uf"])
        if d in by_day:
            if abs(by_day[d] - v) > 1e-9:
                raise ValueError(f"UF conflict on {d}: {by_day[d]} vs {v}")
            duplicates += 1
            continue
        by_day[d] = v

    # Drop values that move implausibly far from the last *valid* value. Compare
    # against the last valid one, not the previous raw one: two corrupted days in
    # a row (as in 2014-12-29/30) would otherwise validate each other.
    outliers: list[date] = []
    last_valid: float | None = None
    for d in sorted(by_day):
        v = by_day[d]
        if last_valid is not None and abs(math.log(v / last_valid)) > MAX_DAILY_LOG_MOVE:
            outliers.append(d)
            continue
        last_valid = v
    for d in outliers:
        del by_day[d]

    days = sorted(by_day)
    out: list[tuple[date, float]] = []
    filled: list[date] = []
    for a, b in zip(days, days[1:]):
        out.append((a, by_day[a]))
        gap = (b - a).days
        if gap == 1:
            continue
        if gap - 1 > MAX_GAP_DAYS:
            raise ValueError(f"UF gap too long to interpolate: {a} -> {b}")
        step = (by_day[b] / by_day[a]) ** (1 / gap)
        for k in range(1, gap):
            d = a + timedelta(days=k)
            out.append((d, by_day[a] * step**k))
            filled.append(d)
    out.append((days[-1], by_day[days[-1]]))
    return out, {"duplicates_dropped": duplicates, "outliers_dropped": outliers,
                 "days_interpolated": filled}


def main() -> None:
    rows = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    series, report = clean_uf(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"fecha": [d for d, _ in series],
                  "uf": [v for _, v in series]}).write_parquet(OUT_PATH)
    print(f"duplicados descartados : {report['duplicates_dropped']}")
    print(f"valores imposibles     : {[str(d) for d in report['outliers_dropped']]}")
    print(f"dias interpolados      : {[str(d) for d in report['days_interpolated']]}")
    print(f"-> {OUT_PATH.relative_to(ROOT)} ({len(series):,} dias, "
          f"{series[0][0]} -> {series[-1][0]})")


if __name__ == "__main__":
    main()
