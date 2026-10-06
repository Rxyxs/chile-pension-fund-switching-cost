"""Tests de `analysis/pension_loss.py`.

Casi todos usan series construidas a mano donde la respuesta correcta sale por
aritmética. El primero existe porque la primera versión del módulo tenía un bug
que solo una serie de inicio distinto puede delatar: indexaba cada fondo por
posición desde su propio primer mes, y como el Fondo A empieza en septiembre de
2002 y el E en enero, el precio del E quedaba desfasado ocho meses.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.pension_loss import (  # noqa: E402
    SerieMensual,
    evaluar_cohorte,
    factor_anualidad,
    mes_absoluto,
    simular_carrera,
)


def serie(fondo: str, inicio: date, valores, retorno: float = 0.0) -> SerieMensual:
    return SerieMensual(fondo, mes_absoluto(inicio), tuple(float(v) for v in valores),
                        retorno)


def planas(valor: float = 100.0, meses: int = 600) -> dict[str, SerieMensual]:
    inicio = date(1990, 1, 1)
    return {f: serie(f, inicio, [valor] * meses) for f in ("A", "B", "E")}


def test_indice_en_usa_el_mes_de_calendario_y_no_la_posicion():
    e = serie("E", date(2002, 1, 1), [100 + i for i in range(24)])
    a = serie("A", date(2002, 9, 1), [500 + i for i in range(24)])
    enero_2003 = mes_absoluto(date(2003, 1, 15))
    # Enero de 2003 es la posición 12 de una serie que parte en enero de 2002, y
    # la posición 4 de una que parte en septiembre. Con indexación por posición,
    # los dos fondos devolverían su valor 12 -- meses distintos del calendario.
    assert e.indice_en(enero_2003) == 112
    assert a.indice_en(enero_2003) == 504


def test_con_fondos_identicos_cambiarse_no_cuesta_nada():
    r = evaluar_cohorte(planas(), "x", date(2010, 6, 1), 40, 12)
    assert r.perdida == pytest.approx(0.0, abs=1e-6)
    assert r.efecto_saldo == pytest.approx(0.0, abs=1e-6)
    assert r.efecto_aporte == pytest.approx(0.0, abs=1e-6)


def test_con_fondos_planos_el_saldo_es_la_suma_de_las_cotizaciones():
    # 40 años de cotización (25 a 65, ambos inclusive en meses: 481), sueldo
    # constante si no hay crecimiento -- acá sí hay 1% real anual, así que se
    # compara contra la suma explícita.
    from analysis import pension_loss as pl
    esperado = 0.0
    salario = pl.SALARIO_MENSUAL_UF
    for k in range(481):
        if k > 0 and k % 12 == 0:
            salario *= 1 + pl.CRECIMIENTO_SALARIAL_REAL_ANUAL
        esperado += salario * pl.TASA_COTIZACION
    saldo = simular_carrera(planas(), 40, date(2010, 6, 1), 0)
    assert saldo == pytest.approx(esperado)


def test_la_perdida_porcentual_no_depende_del_sueldo():
    inicio = date(1990, 1, 1)
    # Un fondo de riesgo que cae a la mitad en 2010 y se recupera en 2011.
    a = [100.0] * 240 + [50.0] * 12 + [100.0] * 348
    series = {"A": serie("A", inicio, a), "B": serie("B", inicio, a),
              "E": serie("E", inicio, [100.0] * 600)}
    evento = date(2010, 1, 1)
    chico = simular_carrera(series, 45, evento, 0, salario_inicial=10.0)
    grande = simular_carrera(series, 45, evento, 0, salario_inicial=40.0)
    chico_p = simular_carrera(series, 45, evento, 12, salario_inicial=10.0)
    grande_p = simular_carrera(series, 45, evento, 12, salario_inicial=40.0)
    assert 1 - chico_p / chico == pytest.approx(1 - grande_p / grande)


def test_a_los_56_el_saldo_sale_obligatoriamente_del_fondo_a():
    """Ley 19.795: desde los 56 un hombre no puede tener el obligatorio en el A.

    Se arma un Fondo A que se duplica cuando el afiliado ya tiene 58 años. Si la
    simulación lo dejara en el A, capturaría esa duplicación; como a los 56 debe
    pasar al B (plano), el saldo final tiene que ser el mismo que si el A no se
    hubiera movido nunca.
    """
    inicio = date(1990, 1, 1)
    evento = date(2010, 1, 1)                 # el afiliado tiene 40 acá
    mes_58 = (58 - 40) * 12 + 240             # posición del mes en que cumple 58
    a_duplica = [100.0] * mes_58 + [200.0] * (600 - mes_58)
    con_salto = {"A": serie("A", inicio, a_duplica),
                 "B": serie("B", inicio, [100.0] * 600),
                 "E": serie("E", inicio, [100.0] * 600)}
    saldo = simular_carrera(con_salto, 40, evento, 0)
    assert saldo == pytest.approx(simular_carrera(planas(), 40, evento, 0))


def test_cotizar_al_refugio_mientras_el_riesgo_esta_barato_tiene_costo():
    inicio = date(1990, 1, 1)
    # A cae a 50 justo en el evento, se queda ahí los 12 meses y vuelve a 100.
    a = [100.0] * 240 + [50.0] * 12 + [100.0] * 348
    series = {"A": serie("A", inicio, a), "B": serie("B", inicio, a),
              "E": serie("E", inicio, [100.0] * 600)}
    r = evaluar_cohorte(series, "x", date(2010, 1, 1), 40, 12)
    # Quien se queda compra cuotas a 50 durante doce meses y las ve volver a 100;
    # quien cotiza al E durante esos meses se pierde exactamente eso.
    assert r.efecto_aporte > 0
    assert r.efecto_saldo > 0


def test_la_regla_observable_usa_el_maximo_corrido_y_no_el_inicial():
    """La pérdida se mide contra el máximo alcanzado hasta cada día.

    El índice sube de 100 a 120 y después cae. Contra el valor inicial (100), un
    15% de caída sería 85; contra el máximo corrido (120) es 102. La regla tiene
    que dispararse en 102, que es lo que una persona ve en su cartola: cuánto
    perdió desde lo más alto que llegó a tener.
    """
    import duckdb

    from analysis.pension_loss import fecha_regla_observable

    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE fund_index_real (fondo VARCHAR, fecha DATE, index_value DOUBLE)")
    valores = [100, 110, 120, 110, 103, 101, 90, 85]
    con.executemany("INSERT INTO fund_index_real VALUES ('A', ?, ?)",
                    [(date(2020, 1, 1 + i), float(v)) for i, v in enumerate(valores)])
    # 101 / 120 - 1 = -15,8%: el primer día que cruza -15% es el sexto (101).
    assert fecha_regla_observable(con, date(2020, 1, 1)) == date(2020, 1, 6)
    con.close()


def test_factor_anualidad():
    assert factor_anualidad(1, 0.0) == 12
    r = 0.02 / 12
    assert factor_anualidad(20, 0.02) == pytest.approx((1 - (1 + r) ** -240) / r)
    # Al 2% real, 20 años de 1 UF mensual valen hoy cerca de 198 UF.
    assert 197 < factor_anualidad(20, 0.02) < 198
