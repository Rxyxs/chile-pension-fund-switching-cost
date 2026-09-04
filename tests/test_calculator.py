"""Tests for scripts/calculator.py's interactive flow, using an injected
input_fn/output_fn (same pattern used for the mining-ops-agent's REPL) so it
can be exercised without a real terminal, against a small hand-built
in-memory fund_index fixture with fully known values."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from calculator import _ask_date, _ask_fund, _ask_int, run_calculator  # noqa: E402


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE fund_index (fondo VARCHAR, fecha DATE, index_value DOUBLE)")
    rows = [
        # Fund A: 100 -> crashes to 50 (-50%, a real episode) -> recovers to 120 -> 130
        ("A", "2020-01-01", 100.0),
        ("A", "2020-06-01", 50.0),
        ("A", "2021-06-01", 120.0),
        ("A", "2021-12-01", 130.0),
        # Fund E: flat, then a small real move
        ("E", "2020-01-01", 100.0),
        ("E", "2020-06-01", 100.0),
        ("E", "2021-06-01", 102.0),
        ("E", "2021-12-01", 103.0),
    ]
    for fondo, fecha, value in rows:
        c.execute("INSERT INTO fund_index VALUES (?, ?, ?)", [fondo, fecha, value])
    yield c
    c.close()


def _scripted_io(inputs: list[str]):
    it = iter(inputs)
    outputs: list[str] = []
    return (lambda _prompt: next(it)), outputs.append, outputs


def test_calculator_selecting_a_real_episode_matches_hand_computed_result(con):
    # 1 = pick the only detected episode, to_fund E, return lag 12 months.
    input_fn, output_fn, outputs = _scripted_io(["1", "E", "12"])

    run_calculator(con, input_fn=input_fn, output_fn=output_fn)

    text = "\n".join(outputs)
    # Hand-computed the same way tests/test_panic_switch_cost.py does:
    # stay: 130/100 = +30.0%; panic: 0.5 * (102/100) * (130/120) - 1 = -44.75%.
    assert "+30.00%" in text
    assert "-44.75%" in text
    assert "74.75" in text  # cost of panic, stay - panic
    assert "Costo del panico" in text


def test_calculator_custom_dates_path_asks_for_from_and_to_fund(con):
    # 0 = custom dates, then entry, trough, from_fund, to_fund, lag.
    input_fn, output_fn, outputs = _scripted_io(["0", "2020-01-01", "2020-06-01", "A", "E", "12"])

    run_calculator(con, input_fn=input_fn, output_fn=output_fn)

    text = "\n".join(outputs)
    assert "+30.00%" in text
    assert "-44.75%" in text


def test_calculator_lists_the_detected_episode_before_asking(con):
    input_fn, output_fn, outputs = _scripted_io(["1", "E", "12"])
    run_calculator(con, input_fn=input_fn, output_fn=output_fn)

    text = "\n".join(outputs)
    assert "2020-01-01" in text
    assert "2020-06-01" in text
    assert "50.0%" in text  # max_drawdown_pct for this fixture


def test_ask_int_retries_on_non_numeric_then_out_of_range_then_accepts():
    inputs = iter(["abc", "99", "2"])
    outputs: list[str] = []
    result = _ask_int(lambda _p: next(inputs), outputs.append, "n? ", 1, 3)
    assert result == 2
    assert len(outputs) == 2  # one complaint for "abc", one for out-of-range "99"


def test_ask_fund_rejects_invalid_and_excluded_fund():
    inputs = iter(["Z", "A", "B"])
    outputs: list[str] = []
    result = _ask_fund(lambda _p: next(inputs), outputs.append, "fund? ", exclude="A")
    assert result == "B"
    assert len(outputs) == 2  # "Z" invalid, "A" excluded


def test_ask_date_rejects_bad_format_then_accepts():
    inputs = iter(["not-a-date", "2020-06-01"])
    outputs: list[str] = []
    result = _ask_date(lambda _p: next(inputs), outputs.append, "date? ")
    assert result.isoformat() == "2020-06-01"
    assert len(outputs) == 1
