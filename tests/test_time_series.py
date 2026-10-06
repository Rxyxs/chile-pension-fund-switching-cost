"""Tests de `analysis/time_series.py`.

No prueban que un GARCH converja -- eso es trabajo de `arch` -- sino las tres
decisiones de este módulo que, mal tomadas, producen resultados plausibles y
falsos. Las tres se cometieron de verdad en la primera versión:

- tratar sábados y domingos como días de mercado,
- contar como decisiones distintas varias señales del mismo episodio,
- ejecutar el traspaso al precio del día de la señal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.time_series import (  # noqa: E402
    episodios_turbulentos,
    estrategia_con_senal,
    refugio_en_episodios,
    retornos_log,
)


def test_los_retornos_diarios_excluyen_fines_de_semana_pero_no_su_devengo():
    # Índice calendario: sube 1% cada día hábil y 0,01% cada sábado y domingo.
    fechas = pd.date_range("2024-01-01", "2024-01-31", freq="D")
    crec = [1.01 if d.dayofweek < 5 else 1.0001 for d in fechas]
    indice = pd.Series(np.cumprod(crec) * 100, index=fechas, name="A")
    r = retornos_log(indice)
    assert (r.index.dayofweek < 5).all()
    # El retorno de un lunes es viernes -> lunes: incluye el devengo del fin de
    # semana, no lo pierde.
    lunes = r[r.index.dayofweek == 0]
    esperado = np.log(1.0001 * 1.0001 * 1.01) * 100
    assert lunes.iloc[0] == pytest.approx(esperado)


def _escenario(prob: list[float], a: list[float], e: list[float]):
    idx = pd.date_range("2020-01-03", periods=len(prob), freq="W-FRI")
    return (pd.Series(prob, index=idx), pd.Series(a, index=idx, name="A"),
            pd.Series(e, index=idx, name="E"))


def test_senales_dentro_de_un_mismo_periodo_afuera_son_una_sola_decision():
    # La probabilidad cruza 0,5 en la semana 1 y otra vez en la 4. Con 10
    # semanas afuera, la segunda señal ocurre estando ya afuera: no es una nueva
    # decisión.
    prob = [0.1, 0.9, 0.2, 0.3, 0.8] + [0.1] * 15
    a = list(np.linspace(100, 120, 20))
    e = [100.0] * 20
    p, sa, se = _escenario(prob, a, e)
    r = estrategia_con_senal(p, sa, se, semanas_fuera=10, rezago_ejecucion=0)
    assert r["n_decisiones"] == 1


def test_el_traspaso_se_ejecuta_con_rezago_y_no_al_precio_de_la_senal():
    # El A rebota fuerte justo la semana siguiente a la señal. Sin rezago, la
    # salida ocurre antes del rebote; con rezago de 1 semana, ya ocurrió.
    prob = [0.1, 0.9] + [0.1] * 10
    a = [100.0, 80.0, 100.0] + [100.0] * 9
    e = [100.0] * 12
    p, sa, se = _escenario(prob, a, e)
    sin = estrategia_con_senal(p, sa, se, semanas_fuera=5, rezago_ejecucion=0)
    con = estrategia_con_senal(p, sa, se, semanas_fuera=5, rezago_ejecucion=1)
    # Saliendo a 80 y quedando el A en 100 al volver: salir costó 25 pp.
    assert sin["detalle"][0]["costo_de_salir_pp"] == pytest.approx(25.0)
    # Saliendo ya a 100: el A no se mueve después, salir no costó nada.
    assert con["detalle"][0]["costo_de_salir_pp"] == pytest.approx(0.0)


def test_episodios_cortos_no_cuentan_como_episodio():
    idx = pd.date_range("2020-01-03", periods=12, freq="W-FRI")
    prob = pd.Series([0.1, 0.9, 0.9, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1],
                     index=idx)
    eps = episodios_turbulentos(prob, min_semanas=4)
    assert len(eps) == 1
    assert eps[0][2] == 5


def test_refugio_mide_el_retorno_dentro_del_episodio():
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    a = pd.Series(np.linspace(100, 80, 10), index=idx)
    e = pd.Series(np.linspace(100, 105, 10), index=idx)
    x = refugio_en_episodios([(str(idx[0].date()), str(idx[-1].date()), 1)], a, e)[0]
    assert x["a_pct"] == pytest.approx(-20.0)
    assert x["e_pct"] == pytest.approx(5.0)
