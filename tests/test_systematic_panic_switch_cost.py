"""Tests for analysis/systematic_panic_switch_cost.py's scenario builder."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from systematic_panic_switch_cost import build_systematic_scenarios  # noqa: E402


def _make_con(rows: list[tuple[str, str, float]]) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE fund_index (fondo VARCHAR, fecha DATE, index_value DOUBLE)")
    for fondo, fecha, value in rows:
        c.execute("INSERT INTO fund_index VALUES (?, ?, ?)", [fondo, fecha, value])
    return c


def test_builds_one_scenario_per_episode_times_lag():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-06-01", 70.0),  # episode 1 trough (-30%)
            ("A", "2020-12-01", 100.0),  # episode 1 recovers
            ("E", "2020-01-01", 100.0),
            ("E", "2020-06-01", 100.0),
            ("E", "2020-12-01", 100.0),
        ]
    )
    lag_grid = (3, 6, 12)
    scenarios, episodes = build_systematic_scenarios(con, lag_grid_months=lag_grid, threshold_pct=15.0)

    assert len(episodes) == 1
    assert len(scenarios) == len(lag_grid)
    assert {s.return_lag_months for s in scenarios} == set(lag_grid)
    for s in scenarios:
        assert s.entry_date == date(2020, 1, 1)
        assert s.trough_date == date(2020, 6, 1)
        assert s.from_fund == "A"
        assert s.to_fund == "E"
    con.close()


def test_unrecovered_episode_is_excluded_from_scenarios():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-06-01", 70.0),  # still underwater at the last row -- no recovery_date
        ]
    )
    scenarios, episodes = build_systematic_scenarios(con, lag_grid_months=(3, 6), threshold_pct=15.0)

    assert episodes == []  # find_drawdown_episodes still returns it, but as unrecovered
    assert scenarios == []
    con.close()


def test_two_episodes_times_two_lags_gives_four_scenarios():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-03-01", 80.0),  # episode 1
            ("A", "2020-06-01", 100.0),
            ("A", "2020-07-01", 130.0),  # genuine new high
            ("A", "2020-09-01", 100.0),  # episode 2 (-23.1% from 130)
            ("A", "2020-12-01", 130.0),
        ]
    )
    scenarios, episodes = build_systematic_scenarios(con, lag_grid_months=(6, 12), threshold_pct=15.0)

    assert len(episodes) == 2
    assert len(scenarios) == 4
    con.close()


def test_exit_date_is_return_date_plus_post_return_horizon():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-06-01", 70.0),
            ("A", "2020-12-01", 100.0),
        ]
    )
    scenarios, _episodes = build_systematic_scenarios(
        con, lag_grid_months=(6,), post_return_horizon_months=3, threshold_pct=15.0
    )

    assert len(scenarios) == 1
    s = scenarios[0]
    # trough 2020-06-01 + 6 months lag = return_date 2020-12-01; + 3 months horizon = exit 2021-03-01
    assert s.return_lag_months == 6
    assert s.exit_date == date(2021, 3, 1)
    con.close()
