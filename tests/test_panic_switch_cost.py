"""Tests for analysis/panic_switch_cost.py — the panic-switch counterfactual simulation."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from panic_switch_cost import SwitchScenario, simulate_panic_switch  # noqa: E402


@pytest.fixture
def con():
    """A hand-built, fully known fund_index so the simulation's arithmetic can be checked exactly."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE fund_index (fondo VARCHAR, fecha DATE, index_value DOUBLE)")
    rows = [
        # Fund A: 100 -> crashes to 50 at the trough -> recovers to 120 a year later
        ("A", "2020-01-01", 100.0),
        ("A", "2020-06-01", 50.0),   # trough
        ("A", "2021-06-01", 120.0),  # return_date (+12mo from trough)
        ("A", "2021-12-01", 130.0),  # exit_date
        # Fund E: flat the whole time
        ("E", "2020-01-01", 100.0),
        ("E", "2020-06-01", 100.0),  # trough
        ("E", "2021-06-01", 102.0),  # return_date
        ("E", "2021-12-01", 103.0),
    ]
    for fondo, fecha, value in rows:
        c.execute("INSERT INTO fund_index VALUES (?, ?, ?)", [fondo, fecha, value])
    yield c
    c.close()


def test_stay_growth_matches_simple_index_ratio(con):
    scenario = SwitchScenario(
        name="test", from_fund="A", to_fund="E",
        entry_date=date(2020, 1, 1), trough_date=date(2020, 6, 1),
        return_lag_months=12, exit_date=date(2021, 12, 1),
    )
    result = simulate_panic_switch(con, scenario)
    # stay in A the whole time: 100 -> 130 = +30%
    assert result["stay_growth_pct"] == pytest.approx(30.0, abs=0.01)


def test_panic_switch_growth_is_worse_when_origin_fund_recovers_sharply(con):
    scenario = SwitchScenario(
        name="test", from_fund="A", to_fund="E",
        entry_date=date(2020, 1, 1), trough_date=date(2020, 6, 1),
        return_lag_months=12, exit_date=date(2021, 12, 1),
    )
    result = simulate_panic_switch(con, scenario)

    # leg 1 (A, entry->trough): 100 -> 50 = 0.5x
    # leg 2 (E, trough->return): 100 -> 102 = 1.02x
    # leg 3 (A, return->exit): 120 -> 130 = 1.0833..x
    expected_panic_multiple = 0.5 * 1.02 * (130.0 / 120.0)
    assert result["panic_growth_pct"] == pytest.approx((expected_panic_multiple - 1) * 100, abs=0.01)
    assert result["panic_growth_pct"] < result["stay_growth_pct"]
    assert result["cost_of_panic_pct_pts"] > 0


def test_raises_if_return_date_exceeds_exit_date(con):
    scenario = SwitchScenario(
        name="test", from_fund="A", to_fund="E",
        entry_date=date(2020, 1, 1), trough_date=date(2020, 6, 1),
        return_lag_months=24,  # would land after exit_date
        exit_date=date(2021, 12, 1),
    )
    with pytest.raises(ValueError, match="return_date must be on or before exit_date"):
        simulate_panic_switch(con, scenario)
