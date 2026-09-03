"""Quantify the real cost of panic-switching multifondos during a market crash.

Uses the patrimonio-weighted fund_index built by etl/build_duckdb.py (real valor_cuota
data, Superintendencia de Pensiones, 2002-2026). For each documented crisis, this compares
two real, back-tested paths over the same window:

  - STAY: money stays in the origin fund the whole time.
  - PANIC: money moves to a safer fund at the crash trough (the point where fear and
    realized losses are highest — the empirically documented moment retail switching
    actually spikes, not the crash's first day) and moves back only `return_lag_months`
    later, once the recovery already happened.

No synthetic assumption about the price path — only real index levels on real calendar
dates, looked up from the DuckDB table built by etl/build_duckdb.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from dateutil.relativedelta import relativedelta

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"


@dataclass(frozen=True)
class SwitchScenario:
    name: str
    from_fund: str
    to_fund: str
    entry_date: date
    trough_date: date
    return_lag_months: int
    exit_date: date


def _index_on_or_before(con: duckdb.DuckDBPyConnection, fondo: str, d: date) -> float:
    row = con.execute(
        "SELECT index_value FROM fund_index WHERE fondo = ? AND fecha <= ? ORDER BY fecha DESC LIMIT 1",
        [fondo, d],
    ).fetchone()
    if row is None:
        raise ValueError(f"no index value for fondo={fondo} on or before {d}")
    return row[0]


def simulate_panic_switch(con: duckdb.DuckDBPyConnection, scenario: SwitchScenario) -> dict:
    return_date = scenario.trough_date + relativedelta(months=scenario.return_lag_months)
    if return_date > scenario.exit_date:
        raise ValueError("return_date must be on or before exit_date")

    from_at_entry = _index_on_or_before(con, scenario.from_fund, scenario.entry_date)
    from_at_trough = _index_on_or_before(con, scenario.from_fund, scenario.trough_date)
    from_at_exit = _index_on_or_before(con, scenario.from_fund, scenario.exit_date)
    to_at_trough = _index_on_or_before(con, scenario.to_fund, scenario.trough_date)
    to_at_return = _index_on_or_before(con, scenario.to_fund, return_date)
    from_at_return = _index_on_or_before(con, scenario.from_fund, return_date)

    stay_value = from_at_exit / from_at_entry

    value_at_trough = from_at_trough / from_at_entry
    value_after_safe_leg = value_at_trough * (to_at_return / to_at_trough)
    value_after_return_leg = value_after_safe_leg * (from_at_exit / from_at_return)
    panic_value = value_after_return_leg

    return {
        "scenario": scenario.name,
        "from_fund": scenario.from_fund,
        "to_fund": scenario.to_fund,
        "entry_date": scenario.entry_date.isoformat(),
        "trough_date": scenario.trough_date.isoformat(),
        "return_date": return_date.isoformat(),
        "exit_date": scenario.exit_date.isoformat(),
        "stay_growth_pct": round((stay_value - 1) * 100, 2),
        "panic_growth_pct": round((panic_value - 1) * 100, 2),
        "cost_of_panic_pct_pts": round((stay_value - panic_value) * 100, 2),
    }


SCENARIOS = [
    SwitchScenario(
        name="GFC 2008 (A -> E, vuelve a los 12 meses)",
        from_fund="A", to_fund="E",
        entry_date=date(2008, 3, 1),
        trough_date=date(2008, 11, 20),
        return_lag_months=12,
        exit_date=date(2010, 3, 1),
    ),
    SwitchScenario(
        name="COVID 2020 (A -> E, vuelve a los 6 meses)",
        from_fund="A", to_fund="E",
        entry_date=date(2019, 9, 1),
        trough_date=date(2020, 3, 23),
        return_lag_months=6,
        exit_date=date(2021, 3, 1),
    ),
    SwitchScenario(
        name="COVID 2020 (A -> E, vuelve a los 12 meses)",
        from_fund="A", to_fund="E",
        entry_date=date(2019, 9, 1),
        trough_date=date(2020, 3, 23),
        return_lag_months=12,
        exit_date=date(2021, 9, 1),
    ),
    SwitchScenario(
        name="Alza de tasas 2022 (A -> E, vuelve a los 12 meses)",
        from_fund="A", to_fund="E",
        entry_date=date(2021, 6, 1),
        trough_date=date(2022, 10, 20),
        return_lag_months=12,
        exit_date=date(2023, 12, 1),
    ),
]


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    results = [simulate_panic_switch(con, s) for s in SCENARIOS]
    con.close()

    import polars as pl

    df = pl.DataFrame(results)
    out_path = REPORTS_DIR / "panic_switch_results.csv"
    df.write_csv(out_path)

    for r in results:
        print(
            f"{r['scenario']}: quedarse {r['stay_growth_pct']:+.1f}% vs. "
            f"pánico {r['panic_growth_pct']:+.1f}% "
            f"(costo del pánico: {r['cost_of_panic_pct_pts']:.1f} puntos porcentuales)"
        )
    print(f"-> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
