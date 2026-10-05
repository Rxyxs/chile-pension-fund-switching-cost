"""Tests de `analysis/timing_grid.py`.

El módulo responde "¿a partir de cuánta pérdida ya sufrida deja de servir
cambiarse?", y la respuesta sale de una simulación de tres tramos. Un error de
signo o un tramo mal encadenado daría un resultado plausible y silenciosamente
invertido, así que acá se verifica contra escenarios construidos a mano donde la
respuesta correcta se conoce por aritmética, no por correr el pipeline.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.timing_grid import simulate_at  # noqa: E402


@pytest.fixture()
def con():
    """Mini índice de dos fondos con valores elegidos para que las cuentas salgan redondas."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE fund_index (fondo VARCHAR, fecha DATE, index_value DOUBLE)")
    rows = [
        # Fondo A: 100 -> 50 (cae a la mitad) -> 200 (se cuadruplica desde el piso)
        ("A", date(2020, 1, 1), 100.0),
        ("A", date(2020, 2, 1), 80.0),
        ("A", date(2020, 3, 1), 50.0),
        ("A", date(2020, 6, 1), 200.0),
        # Fondo E: plano en 100 todo el período
        ("E", date(2020, 1, 1), 100.0),
        ("E", date(2020, 2, 1), 100.0),
        ("E", date(2020, 3, 1), 100.0),
        ("E", date(2020, 6, 1), 100.0),
    ]
    c.executemany("INSERT INTO fund_index VALUES (?, ?, ?)", rows)
    yield c
    c.close()


def test_staying_is_the_full_path_of_the_original_fund(con):
    stay, _ = simulate_at(con, date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 6, 1))
    # 100 -> 200 es +100%, sin importar lo que pase en el medio.
    assert stay == pytest.approx(100.0)


def test_switching_into_a_flat_fund_locks_in_the_loss_taken_so_far(con):
    # Se cambia habiendo perdido 20% (100 -> 80) y vuelve en el piso (50).
    # Tramo 1: 100 -> 80  = x0.8
    # Tramo 2: E plano    = x1.0
    # Tramo 3: 50 -> 200  = x4.0
    # Total: 0.8 * 1.0 * 4.0 = 3.2 -> +220%
    _, switch = simulate_at(con, date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 6, 1))
    assert switch == pytest.approx(220.0)


def test_switching_early_beats_staying_when_the_fall_continues(con):
    # Salir al 20% de pérdida y volver en el piso esquiva el tramo 80 -> 50.
    stay, switch = simulate_at(con, date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 6, 1))
    assert switch > stay
    assert stay - switch == pytest.approx(-120.0)  # costo negativo = cambiarse ganó


def test_switching_at_the_trough_and_returning_at_the_trough_changes_nothing(con):
    # Si el fondo de refugio no se mueve entre el cambio y el retorno, y ambos
    # ocurren el mismo día, cambiarse tiene que ser exactamente igual a quedarse.
    stay, switch = simulate_at(con, date(2020, 1, 1), date(2020, 3, 1), date(2020, 3, 1), date(2020, 6, 1))
    assert switch == pytest.approx(stay)


def test_switching_at_the_trough_and_returning_late_forfeits_the_recovery(con):
    # Se cambia en el piso (50) y vuelve recién al final (200): se pierde toda la
    # recuperación y queda el x0.5 de la caída.
    # 100 -> 50 = x0.5, E plano, y vuelve justo al cierre -> no recupera nada.
    stay, switch = simulate_at(con, date(2020, 1, 1), date(2020, 3, 1), date(2020, 6, 1), date(2020, 6, 1))
    assert switch == pytest.approx(-50.0)
    assert stay - switch == pytest.approx(150.0)  # costo positivo y grande


def test_the_safe_fund_return_between_switch_and_return_is_credited(con):
    """Si el fondo de refugio sube mientras se está en él, esa ganancia cuenta."""
    con.execute("UPDATE fund_index SET index_value = 110.0 WHERE fondo = 'E' AND fecha = DATE '2020-03-01'")
    _, switch = simulate_at(con, date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 6, 1))
    # 0.8 * (110/100) * 4.0 = 3.52 -> +252%
    assert switch == pytest.approx(252.0)


def test_index_lookup_uses_the_last_value_on_or_before_the_date(con):
    """Las fechas de la grilla caen en días sin dato (fines de semana, feriados).

    La simulación tiene que tomar el último valor disponible hacia atrás, no
    fallar ni interpolar hacia adelante -- interpolar usaría un precio futuro.
    """
    # 2020-02-15 no existe en la tabla; debe resolverse al valor del 2020-02-01.
    stay_a, switch_a = simulate_at(con, date(2020, 1, 1), date(2020, 2, 15), date(2020, 3, 1), date(2020, 6, 1))
    stay_b, switch_b = simulate_at(con, date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1), date(2020, 6, 1))
    assert switch_a == pytest.approx(switch_b)
    assert stay_a == pytest.approx(stay_b)
