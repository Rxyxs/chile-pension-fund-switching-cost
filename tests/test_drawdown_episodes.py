"""Tests for analysis/drawdown_episodes.py, using small hand-built in-memory
DuckDB fixtures with fully known values (same pattern as
tests/test_panic_switch_cost.py) so the episode boundaries can be checked
exactly rather than just "some episode was found somewhere"."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from drawdown_episodes import find_drawdown_episodes  # noqa: E402


def _make_con(rows: list[tuple[str, str, float]]) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE fund_index (fondo VARCHAR, fecha DATE, index_value DOUBLE)")
    for fondo, fecha, value in rows:
        c.execute("INSERT INTO fund_index VALUES (?, ?, ?)", [fondo, fecha, value])
    return c


def test_finds_one_completed_episode_above_threshold():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-03-01", 105.0),  # new peak
            ("A", "2020-06-01", 80.0),  # -23.8% from peak -- crosses 15% threshold
            ("A", "2020-08-01", 75.0),  # deeper trough, -28.6%
            ("A", "2020-12-01", 105.0),  # fully recovered to the 105 peak
        ]
    )
    episodes = find_drawdown_episodes(con, "A", threshold_pct=15.0)

    assert len(episodes) == 1
    ep = episodes[0]
    assert ep.peak_date == date(2020, 3, 1)
    assert ep.peak_value == 105.0
    assert ep.trough_date == date(2020, 8, 1)
    assert ep.trough_value == 75.0
    assert ep.recovery_date == date(2020, 12, 1)
    assert ep.max_drawdown_pct == round((1 - 75.0 / 105.0) * 100, 2)
    con.close()


def test_dip_below_threshold_is_not_flagged():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-03-01", 90.0),  # only -10%, below the 15% threshold
            ("A", "2020-06-01", 110.0),  # new high
        ]
    )
    episodes = find_drawdown_episodes(con, "A", threshold_pct=15.0)
    assert episodes == []
    con.close()


def test_unrecovered_drawdown_at_end_of_data_has_no_recovery_date():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-06-01", 70.0),  # -30%, still underwater at the last row
        ]
    )
    episodes = find_drawdown_episodes(con, "A", threshold_pct=15.0)

    assert len(episodes) == 1
    assert episodes[0].recovery_date is None
    assert episodes[0].trough_value == 70.0
    con.close()


def test_intermediate_bounce_that_does_not_fully_recover_stays_one_episode():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-03-01", 80.0),  # -20%, enters drawdown
            ("A", "2020-05-01", 95.0),  # partial bounce, still below the 100 peak
            ("A", "2020-07-01", 70.0),  # deeper trough than the initial one
            ("A", "2020-09-01", 100.0),  # full recovery
        ]
    )
    episodes = find_drawdown_episodes(con, "A", threshold_pct=15.0)

    # A single episode, not two -- the partial bounce to 95 never reached the
    # original 100 peak, so it doesn't end the episode.
    assert len(episodes) == 1
    assert episodes[0].trough_date == date(2020, 7, 1)
    assert episodes[0].trough_value == 70.0
    assert episodes[0].recovery_date == date(2020, 9, 1)
    con.close()


def test_two_separate_episodes_split_by_a_genuine_new_high():
    con = _make_con(
        [
            ("A", "2020-01-01", 100.0),
            ("A", "2020-03-01", 80.0),  # episode 1 trough
            ("A", "2020-06-01", 100.0),  # episode 1 recovers
            ("A", "2020-07-01", 120.0),  # genuine new high -- resets the peak
            ("A", "2020-09-01", 95.0),  # -20.8% from the new 120 peak -- episode 2
            ("A", "2020-12-01", 120.0),  # episode 2 recovers
        ]
    )
    episodes = find_drawdown_episodes(con, "A", threshold_pct=15.0)

    assert len(episodes) == 2
    assert episodes[0].peak_value == 100.0
    assert episodes[0].trough_value == 80.0
    assert episodes[1].peak_value == 120.0
    assert episodes[1].trough_value == 95.0
    con.close()


def test_empty_table_returns_no_episodes():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE fund_index (fondo VARCHAR, fecha DATE, index_value DOUBLE)")
    assert find_drawdown_episodes(con, "A") == []
    con.close()
