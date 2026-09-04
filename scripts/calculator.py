"""Interactive calculator: pick a real detected drawdown episode (or your own
dates) and see what panic-switching funds would really have cost -- computed
against the same real Superintendencia de Pensiones daily data as the rest
of this repo, not a rule of thumb.

    python scripts/calculator.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
from dateutil.relativedelta import relativedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from drawdown_episodes import DrawdownEpisode, find_drawdown_episodes  # noqa: E402
from panic_switch_cost import SwitchScenario, simulate_panic_switch  # noqa: E402

DB_PATH = ROOT / "data" / "pension_funds.duckdb"
FUNDS = ("A", "B", "C", "D", "E")
DEFAULT_THRESHOLD_PCT = 15.0


def _list_episodes(con: duckdb.DuckDBPyConnection, fondo: str = "A") -> list[DrawdownEpisode]:
    return [ep for ep in find_drawdown_episodes(con, fondo, DEFAULT_THRESHOLD_PCT) if ep.recovery_date is not None]


def _ask_int(input_fn: Any, output_fn: Any, prompt: str, low: int, high: int) -> int | None:
    while True:
        raw = input_fn(prompt).strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            output_fn(f"Ingresa un numero entre {low} y {high}.")
            continue
        if low <= value <= high:
            return value
        output_fn(f"Ingresa un numero entre {low} y {high}.")


def _ask_fund(input_fn: Any, output_fn: Any, prompt: str, exclude: str | None = None) -> str:
    while True:
        raw = input_fn(prompt).strip().upper()
        if raw in FUNDS and raw != exclude:
            return raw
        output_fn(f"Ingresa una letra de fondo valida (A-E){f', distinta de {exclude}' if exclude else ''}.")


def _ask_date(input_fn: Any, output_fn: Any, prompt: str) -> date:
    while True:
        raw = input_fn(prompt).strip()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            output_fn("Formato de fecha invalido, usa AAAA-MM-DD (ej. 2020-03-23).")


def run_calculator(con: duckdb.DuckDBPyConnection, input_fn: Any = input, output_fn: Any = print) -> None:
    episodes = _list_episodes(con)

    output_fn(f"Caidas reales del Fondo A detectadas en los datos (>= {DEFAULT_THRESHOLD_PCT:.0f}%, 2002-2026):\n")
    for i, ep in enumerate(episodes, start=1):
        output_fn(
            f"  {i}. Pico {ep.peak_date} -> Piso {ep.trough_date} "
            f"(caida real {ep.max_drawdown_pct:.1f}%, recuperado el {ep.recovery_date})"
        )
    output_fn(f"  0. Ingresar mis propias fechas\n")

    choice = _ask_int(input_fn, output_fn, "Elegi una caida (numero): ", 0, len(episodes))

    if choice == 0:
        entry_date = _ask_date(input_fn, output_fn, "Fecha de entrada (AAAA-MM-DD, antes de la caida): ")
        trough_date = _ask_date(input_fn, output_fn, "Fecha del piso/panico (AAAA-MM-DD): ")
    else:
        ep = episodes[choice - 1]
        entry_date, trough_date = ep.peak_date, ep.trough_date
        output_fn(f"\nUsando: pico {entry_date} -> piso {trough_date} (caida real {ep.max_drawdown_pct:.1f}%)\n")

    from_fund = _ask_fund(input_fn, output_fn, "Fondo de origen (A-E, por defecto A): ") if choice == 0 else "A"
    to_fund = _ask_fund(input_fn, output_fn, "Fondo al que te cambiarias en panico (A-E): ", exclude=from_fund)
    return_lag_months = _ask_int(
        input_fn, output_fn, "Meses hasta volver al fondo de origen (ej. 12): ", 1, 60
    )
    exit_date = trough_date + relativedelta(months=return_lag_months + 12)

    scenario = SwitchScenario(
        name="calculadora interactiva",
        from_fund=from_fund,
        to_fund=to_fund,
        entry_date=entry_date,
        trough_date=trough_date,
        return_lag_months=return_lag_months,
        exit_date=exit_date,
    )

    try:
        result = simulate_panic_switch(con, scenario)
    except ValueError as exc:
        output_fn(f"\nNo se pudo calcular: {exc}")
        return

    output_fn(f"\nResultado real, {entry_date} -> {exit_date} (Fondo {from_fund}, panico a Fondo {to_fund}, {return_lag_months} meses):")
    output_fn(f"  Te quedas en {from_fund}:        {result['stay_growth_pct']:+.2f}%")
    output_fn(f"  Te cambias en panico a {to_fund}: {result['panic_growth_pct']:+.2f}%")
    if result["cost_of_panic_pct_pts"] > 0:
        output_fn(f"  Costo del panico: {result['cost_of_panic_pct_pts']:.2f} puntos porcentuales peor que quedarte.")
    elif result["cost_of_panic_pct_pts"] < 0:
        output_fn(f"  En este escenario, cambiarse en panico salio {-result['cost_of_panic_pct_pts']:.2f} puntos porcentuales MEJOR que quedarte.")
    else:
        output_fn("  En este escenario, quedarse y cambiarse dieron el mismo resultado.")


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"No se encontro {DB_PATH}. Corre primero: python etl/build_duckdb.py", file=sys.stderr)
        raise SystemExit(1)

    real_con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        run_calculator(real_con)
    finally:
        real_con.close()
