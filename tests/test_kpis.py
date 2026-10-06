"""Tests de `analysis/kpis.py`.

Los indicadores se verifican contra caminos construidos a mano donde el valor
correcto sale por aritmética: un drawdown conocido, una regla que tiene que
dispararse una sola vez por caída, una salida que no puede solaparse con otra.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.kpis import (  # noqa: E402
    camino_estrategia,
    estadisticas_de_decisiones,
    eventos_regla_observable,
    eventos_regla_piso,
    kpis_de_camino,
    mascara_de_eventos,
)


def _semanal(valores) -> pd.Series:
    return pd.Series(valores, index=pd.date_range("2010-01-01", periods=len(valores), freq="W-FRI"),
                     dtype=float)


def test_drawdown_maximo_y_recuperacion():
    # 100 -> 120 (máximo) -> 90 (piso, -25%) -> 120 (recupera) -> 130
    camino = _semanal([100, 110, 120, 105, 90, 100, 120, 130])
    k = kpis_de_camino(camino)
    assert k["drawdown_max_pct"] == pytest.approx(-25.0)
    assert k["drawdown_max_desde"] == str(camino.index[2].date())
    assert k["drawdown_max_piso"] == str(camino.index[4].date())
    assert k["drawdown_max_recuperado"] == str(camino.index[6].date())


def test_un_camino_que_nunca_se_recupera_queda_bajo_el_agua_hasta_el_final():
    camino = _semanal([100, 120, 80, 90, 100])
    k = kpis_de_camino(camino)
    assert k["drawdown_max_recuperado"] is None
    esperado = (camino.index[-1] - camino.index[1]).days / 30.44
    assert k["meses_bajo_el_agua"] == pytest.approx(esperado)


def test_la_tasa_libre_de_riesgo_baja_el_sharpe_en_la_magnitud_esperada():
    rng = np.random.default_rng(0)
    camino = _semanal(100 * np.cumprod(1 + rng.normal(0.002, 0.02, 520)))
    k = kpis_de_camino(camino)
    # Sharpe(rf) = (media - rf) / vol, así que bajar de 0% a 1% resta 0,01 / vol.
    assert k["sharpe"] - k["sharpe_rf1"] == pytest.approx(1.0 / k["volatilidad_pct"])


def test_la_regla_observable_se_dispara_una_sola_vez_por_caida():
    # Cae 20% (se dispara), sigue cayendo, rebota sin llegar al máximo y vuelve
    # a caer: sigue siendo la MISMA caída, no hay segunda señal. Recién después
    # de un máximo nuevo puede haber otra.
    nivel = np.array([100, 90, 80, 75, 85, 70, 100, 101, 85, 80], dtype=float)
    assert eventos_regla_observable(nivel) == [2, 8]


def test_el_piso_solo_cuenta_caidas_que_se_recuperaron():
    # La primera caída (a 70) se recupera en 100; la segunda (a 60) nunca vuelve.
    nivel = np.array([100, 85, 70, 90, 100, 110, 80, 60, 70], dtype=float)
    assert eventos_regla_piso(nivel) == [2]


def test_una_senal_estando_afuera_no_es_una_nueva_decision():
    en_e, tramos = mascara_de_eventos([2, 5], n=40, rezago=1, semanas_fuera=10)
    assert tramos == [(3, 13)]
    # Afuera las semanas 4..13: la que se ejecuta al cierre de la 3 rinde desde la 4.
    assert en_e[3] is np.False_ and en_e[4] is np.True_ and en_e[13] is np.True_
    assert en_e[14] is np.False_


def test_una_decision_que_no_alcanza_a_completarse_se_descarta():
    _, tramos = mascara_de_eventos([35], n=40, rezago=1, semanas_fuera=10)
    assert tramos == []


def test_tasa_de_acierto_y_payoff():
    ret_a = np.zeros(30)
    ret_e = np.zeros(30)
    # Primera salida: el A cae 10% y el E queda plano -> salir ganó 10 pp.
    ret_a[2] = -0.10
    # Segunda salida: el A sube 20% -> salir perdió 20 pp.
    ret_a[12] = 0.20
    s = estadisticas_de_decisiones(ret_a, ret_e, [(1, 5), (11, 15)])
    assert s["decisiones"] == 2
    assert s["tasa_acierto_pct"] == pytest.approx(50.0)
    assert s["ganancia_media_al_acertar_pp"] == pytest.approx(10.0)
    assert s["perdida_media_al_fallar_pp"] == pytest.approx(20.0)
    assert s["payoff_ratio"] == pytest.approx(0.5)


def test_camino_estrategia_usa_el_fondo_correcto_cada_semana():
    ret_a = np.array([0.0, 0.10, 0.10, 0.10])
    ret_e = np.array([0.0, 0.00, 0.00, 0.00])
    en_e = np.array([False, False, True, False])
    assert camino_estrategia(ret_a, ret_e, en_e)[-1] == pytest.approx(1.1 * 1.0 * 1.1)
