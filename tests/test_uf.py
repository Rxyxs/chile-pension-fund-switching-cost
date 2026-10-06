"""Tests de `etl/parse_uf.py`.

Los casos reproducen los dos defectos reales de la serie descargada: el día
2015-07-11 repetido cinco veces y los días 2015-12-12 y 2015-12-31 ausentes.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.parse_uf import clean_uf  # noqa: E402


def filas(*pares):
    return [{"fecha": f, "uf": v} for f, v in pares]


def test_duplicados_identicos_se_colapsan():
    serie, rep = clean_uf(filas(
        ("2015-07-10", 25001.96),
        ("2015-07-11", 25005.99), ("2015-07-11", 25005.99), ("2015-07-11", 25005.99),
        ("2015-07-12", 25010.01),
    ))
    assert [d for d, _ in serie] == [date(2015, 7, 10), date(2015, 7, 11), date(2015, 7, 12)]
    assert rep["duplicates_dropped"] == 2


def test_duplicados_que_no_coinciden_son_un_conflicto_y_fallan():
    with pytest.raises(ValueError, match="conflict"):
        clean_uf(filas(("2015-07-11", 25005.99), ("2015-07-11", 25006.50)))


def test_un_dia_faltante_se_interpola_geometricamente():
    # La UF crece a tasa diaria constante dentro de cada período, así que el día
    # faltante es la media geométrica de sus vecinos -- no la aritmética.
    # Valores con un movimiento realista de UF (0,04% diario): un salto mayor
    # sería rechazado como valor imposible antes de llegar a interpolarse.
    serie, rep = clean_uf(filas(("2020-01-01", 10000.0), ("2020-01-03", 10008.0)))
    medio = dict(serie)[date(2020, 1, 2)]
    assert medio * medio == pytest.approx(10000.0 * 10008.0, rel=1e-12)
    assert abs(medio - 10004.0) > 1e-4          # no es la media aritmética
    assert rep["days_interpolated"] == [date(2020, 1, 2)]


def test_un_hueco_largo_no_se_rellena_en_silencio():
    with pytest.raises(ValueError, match="gap too long"):
        clean_uf(filas(("2020-01-01", 100.0), ("2020-01-10", 101.0)))


def test_el_dolar_colado_en_la_serie_se_descarta_y_se_rellena():
    """2014-12-29 y 12-30 traen el dólar observado (~608) en vez de la UF.

    Son dos días corruptos seguidos, así que se valida contra el último valor
    *válido*: comparados entre sí (608,15 -> 607,38) se verían plausibles.
    """
    serie, rep = clean_uf(filas(
        ("2014-12-28", 24627.10),
        ("2014-12-29", 608.15),
        ("2014-12-30", 607.38),
        ("2014-12-31", 24627.10),
    ))
    valores = dict(serie)
    assert rep["outliers_dropped"] == [date(2014, 12, 29), date(2014, 12, 30)]
    assert valores[date(2014, 12, 29)] == pytest.approx(24627.10)
    assert valores[date(2014, 12, 30)] == pytest.approx(24627.10)


def test_la_salida_queda_ordenada_aunque_la_entrada_no():
    serie, _ = clean_uf(filas(("2020-01-02", 101.0), ("2020-01-01", 100.0)))
    assert [d for d, _ in serie] == [date(2020, 1, 1), date(2020, 1, 2)]


def test_valor_de_control_contra_la_tabla_del_sii():
    """Si la descarga real está presente, el 31-12-2008 debe ser 21.452,57."""
    import json
    raw = ROOT / "data" / "raw" / "uf_daily.json"
    if not raw.exists():
        pytest.skip("uf_daily.json no descargado (correr etl/fetch_uf.py)")
    serie, _ = clean_uf(json.loads(raw.read_text(encoding="utf-8")))
    assert dict(serie)[date(2008, 12, 31)] == pytest.approx(21452.57)
