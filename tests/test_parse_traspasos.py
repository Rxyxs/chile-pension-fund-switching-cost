"""Tests for etl/parse_traspasos.py -- the Ficha Estadistica Previsional Tabla N 7 parser."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "etl"))
import parse_traspasos as parser  # noqa: E402


TABLA7_2020_2DIGIT_YEAR = """Tabla N 7
Afiliados y cotizantes
Participacion Participacion Var. anual neta Traspasos netos Ingreso imponible
activos N afiliados N afiliados (1) de cuentas (2) (3) promedio cotizantes
(Oct 20) (Sep 20) (Oct 19 - Sep 20) (Sep 20) (Sep 20)
Capital 19,5% 14,7% -2.041 4.976 897.491
Total 100,0% 100,0% 108.856 0 846.248
(3) El numero total de cuentas
traspasadas entre AFP en agosto de 2020 fue de 24.547."""

TABLA7_2022_4DIGIT_YEAR = """Tabla N 7
Afiliados y cotizantes
Participacion Participacion Var. anual neta N Traspasos netos Ingreso imponible
activos N afiliados afiliados (1) de cuentas (2) (3) promedio cotizantes
(Ago. 2022) (Jul. 2022) (Ago.21 -Jul.22) (Jul. 2022) (Jul. 2022)
Capital 19,8% 13,8% -29.408 -1.608 $1.100.788
Total 100,0% 100,0% 277.810 0 $1.013.519
(3) El numero total de cuentas
traspasadas entre AFP en julio de 2022 fue de 37.964."""


def test_derives_month_from_table_header_not_footnote_prose():
    """This is the real bug this parser exists to work around: the footnote here says
    "agosto de 2020" but the table's own header says the data is for "Sep 20"."""
    data_month, total = parser.parse_tabla7_text(TABLA7_2020_2DIGIT_YEAR)
    assert data_month == "2020-09"
    assert total == 24547


def test_handles_four_digit_year_header_format():
    data_month, total = parser.parse_tabla7_text(TABLA7_2022_4DIGIT_YEAR)
    assert data_month == "2022-07"
    assert total == 37964


def test_returns_none_when_no_tabla7_present():
    data_month, total = parser.parse_tabla7_text("Some unrelated page of the PDF.")
    assert data_month is None
    assert total is None
