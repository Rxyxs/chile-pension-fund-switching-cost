"""Systematic version of panic_switch_cost.py's 4 hand-picked scenarios.

panic_switch_cost.py tells 4 anecdotes (GFC, COVID x2, 2022 rate hikes), each
with one hand-picked return_lag_months. That's a real risk of survivorship
bias in the *selection* of examples -- a human picking "famous crashes" tends
to reach for the ones that make the sharpest panic-switch story. This module
instead: (1) finds every real drawdown episode >= DRAWDOWN_THRESHOLD_PCT in
Fondo A over the full 2002-2026 history programmatically
(drawdown_episodes.py), not by memory, and (2) tests each one against a grid
of plausible return_lag_months, giving a real DISTRIBUTION of the cost of
panic-switching -- including any episode where switching actually turned out
fine, if the real data has one, instead of only the cases a human would
remember to pick.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
from dateutil.relativedelta import relativedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drawdown_episodes import find_drawdown_episodes  # noqa: E402
from panic_switch_cost import SwitchScenario, simulate_panic_switch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"

FROM_FUND = "A"
TO_FUND = "E"
DRAWDOWN_THRESHOLD_PCT = 15.0
RETURN_LAG_GRID_MONTHS: tuple[int, ...] = (3, 6, 12, 18, 24)
POST_RETURN_HORIZON_MONTHS = 12


def build_systematic_scenarios(
    con: duckdb.DuckDBPyConnection,
    from_fund: str = FROM_FUND,
    to_fund: str = TO_FUND,
    threshold_pct: float = DRAWDOWN_THRESHOLD_PCT,
    lag_grid_months: tuple[int, ...] = RETURN_LAG_GRID_MONTHS,
    post_return_horizon_months: int = POST_RETURN_HORIZON_MONTHS,
) -> tuple[list[SwitchScenario], list]:
    """One scenario per (real completed drawdown episode) x (lag in
    lag_grid_months). Episodes still underwater at the end of the data
    (recovery_date is None) are excluded -- there's no real "stay" outcome
    to compare against yet for those. exit_date is always
    return_date + post_return_horizon_months, so every scenario is measured
    over a comparable post-return window regardless of how long the episode
    itself took."""
    episodes = find_drawdown_episodes(con, fondo=from_fund, threshold_pct=threshold_pct)
    completed = [ep for ep in episodes if ep.recovery_date is not None]

    scenarios = []
    for ep in completed:
        for lag in lag_grid_months:
            return_date = ep.trough_date + relativedelta(months=lag)
            exit_date = return_date + relativedelta(months=post_return_horizon_months)
            scenarios.append(
                SwitchScenario(
                    name=f"pico {ep.peak_date} -> piso {ep.trough_date} (caida real {ep.max_drawdown_pct:.1f}%, lag {lag}m)",
                    from_fund=from_fund,
                    to_fund=to_fund,
                    entry_date=ep.peak_date,
                    trough_date=ep.trough_date,
                    return_lag_months=lag,
                    exit_date=exit_date,
                )
            )
    return scenarios, completed


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    scenarios, episodes = build_systematic_scenarios(con)
    results = [simulate_panic_switch(con, s) for s in scenarios]
    con.close()

    import polars as pl

    df = pl.DataFrame(results)
    out_path = REPORTS_DIR / "systematic_panic_switch_results.csv"
    df.write_csv(out_path)

    costs = df["cost_of_panic_pct_pts"]
    n = len(costs)
    n_panic_worse = int((costs > 0).sum())
    n_panic_better = int((costs < 0).sum())

    summary = {
        "n_real_episodes": len(episodes),
        "n_scenarios": n,
        "mean_cost_pct_pts": round(float(costs.mean()), 2),
        "median_cost_pct_pts": round(float(costs.median()), 2),
        "std_cost_pct_pts": round(float(costs.std()), 2),
        "min_cost_pct_pts": round(float(costs.min()), 2),
        "max_cost_pct_pts": round(float(costs.max()), 2),
        "pct_scenarios_panic_worse": round(100 * n_panic_worse / n, 1) if n else 0.0,
        "pct_scenarios_panic_better": round(100 * n_panic_better / n, 1) if n else 0.0,
    }

    import json

    summary_path = REPORTS_DIR / "systematic_panic_switch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(episodes)} caidas reales de Fondo A >= {DRAWDOWN_THRESHOLD_PCT}% detectadas, 2002-2026:")
    for ep in episodes:
        print(f"  {ep.peak_date} -> {ep.trough_date} (caida {ep.max_drawdown_pct:.1f}%, recuperado {ep.recovery_date})")
    print()
    print(f"{n} escenarios (caida real x lag de retorno), costo del panico:")
    print(f"  media {summary['mean_cost_pct_pts']:+.2f} pp, mediana {summary['median_cost_pct_pts']:+.2f} pp, "
          f"desv.est. {summary['std_cost_pct_pts']:.2f} pp")
    print(f"  rango [{summary['min_cost_pct_pts']:+.2f}, {summary['max_cost_pct_pts']:+.2f}] pp")
    print(f"  panico peor en {summary['pct_scenarios_panic_worse']:.1f}% de los escenarios, "
          f"mejor en {summary['pct_scenarios_panic_better']:.1f}%")
    print(f"-> {out_path.relative_to(ROOT)}")
    print(f"-> {summary_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
