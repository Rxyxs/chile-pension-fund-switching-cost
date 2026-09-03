"""Tests for etl/build_duckdb.py — the patrimonio-weighted daily return index."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "etl"))
import build_duckdb as etl  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    long_df = pl.DataFrame(
        {
            "fondo": ["A"] * 6,
            "afp": ["X", "X", "X", "Y", "Y", "Y"],
            "fecha": ["2020-01-01", "2020-01-02", "2020-01-03"] * 2,
            "valor_cuota": [100.0, 110.0, 121.0, 100.0, 90.0, 90.0],
            "valor_patrimonio": [1000.0, 1100.0, 1210.0, 9000.0, 8100.0, 8100.0],
        }
    ).with_columns(pl.col("fecha").str.to_date())

    parquet_path = tmp_path / "valor_cuota_long.parquet"
    long_df.write_parquet(parquet_path)

    monkeypatch.setattr(etl, "PARQUET_PATH", parquet_path)
    monkeypatch.setattr(etl, "DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setattr(etl, "ROOT", tmp_path)
    etl.main()
    con = duckdb.connect(str(tmp_path / "test.duckdb"), read_only=True)
    yield con
    con.close()


def test_weighted_return_favors_the_larger_afp(db):
    """X returns +10% then +10% (small AUM); Y returns -10% then flat (9x the AUM).
    The fondo-level return on day 2 should sit close to Y's return, not the simple average."""
    rows = db.execute(
        "SELECT fecha, weighted_return FROM fund_weighted_returns WHERE fondo='A' ORDER BY fecha"
    ).fetchall()

    day2_return = rows[0][1]  # 2020-01-02: X +10%, Y -10%, weights 1000 vs 9000
    simple_average = (0.10 + (-0.10)) / 2
    assert abs(day2_return - simple_average) > 0.05  # weighted result should NOT equal ~0%
    assert day2_return < 0  # dominated by Y's -10%, since Y has 9x the patrimonio


def test_index_compounds_daily_returns_correctly(db):
    rows = db.execute(
        "SELECT fecha, weighted_return, index_value FROM fund_index WHERE fondo='A' ORDER BY fecha"
    ).fetchall()

    assert all(v is not None for _, _, v in rows)

    running = 100.0
    for _, weighted_return, index_value in rows:
        running *= 1 + weighted_return
        assert index_value == pytest.approx(running, rel=1e-9)
