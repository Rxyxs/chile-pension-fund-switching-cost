"""Build a DuckDB store with a patrimonio-weighted daily return index per fund type (A-E).

Each AFP's valor_cuota is its own price series, rebased to 10,000 CLP independently, so raw
values aren't comparable across AFPs. This aggregates at the return level instead: for each
fund type and day, it computes each AFP's simple daily return, weights those returns by the
AFP's prior-day patrimonio (assets under management), and compounds the weighted-average
return into a single index per fund type — the standard way to build an asset-weighted
benchmark from constituent-level price series.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PARQUET_PATH = ROOT / "data" / "processed" / "valor_cuota_long.parquet"
DB_PATH = ROOT / "data" / "pension_funds.duckdb"


def main() -> None:
    con = duckdb.connect(str(DB_PATH))

    con.execute(
        f"""
        CREATE OR REPLACE TABLE valor_cuota_long AS
        SELECT * FROM read_parquet('{PARQUET_PATH.as_posix()}')
        """
    )

    con.execute(
        """
        CREATE OR REPLACE VIEW afp_daily_returns AS
        SELECT
            fondo, afp, fecha, valor_cuota, valor_patrimonio,
            valor_cuota / lag(valor_cuota) OVER (
                PARTITION BY fondo, afp ORDER BY fecha
            ) - 1 AS simple_return,
            lag(valor_patrimonio) OVER (
                PARTITION BY fondo, afp ORDER BY fecha
            ) AS prior_patrimonio
        FROM valor_cuota_long
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE fund_weighted_returns AS
        SELECT
            fondo,
            fecha,
            sum(simple_return * prior_patrimonio) / nullif(sum(prior_patrimonio), 0) AS weighted_return
        FROM afp_daily_returns
        WHERE simple_return IS NOT NULL AND prior_patrimonio > 0
        GROUP BY fondo, fecha
        HAVING count(*) >= 1
        ORDER BY fondo, fecha
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE fund_index AS
        SELECT
            fondo,
            fecha,
            weighted_return,
            100.0 * exp(sum(ln(1 + weighted_return)) OVER (
                PARTITION BY fondo ORDER BY fecha
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )) AS index_value
        FROM fund_weighted_returns
        ORDER BY fondo, fecha
        """
    )

    for fondo in ["A", "B", "C", "D", "E"]:
        n = con.execute("SELECT count(*) FROM fund_index WHERE fondo = ?", [fondo]).fetchone()[0]
        rng = con.execute(
            "SELECT min(fecha), max(fecha) FROM fund_index WHERE fondo = ?", [fondo]
        ).fetchone()
        print(f"fondo {fondo}: {n:,} dias, {rng[0]} -> {rng[1]}")

    con.close()
    print(f"-> {DB_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
