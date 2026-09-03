"""Tests for etl/parse_valor_cuota.py — the raw valor-cuota text parser."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "etl"))
import parse_valor_cuota as parser  # noqa: E402


def test_parse_clp_number_handles_thousands_and_decimal_separators():
    assert parser._parse_clp_number("96.092,23") == 96092.23
    assert parser._parse_clp_number("10.000,00") == 10000.0
    assert parser._parse_clp_number("1.234.567,89") == 1234567.89


def test_parse_clp_number_returns_none_for_empty_field():
    assert parser._parse_clp_number("") is None
    assert parser._parse_clp_number("   ") is None


def test_parse_fund_file_reanchors_columns_when_header_changes(tmp_path):
    """The real source repeats the header every time the set of active AFPs changes —
    this is the bug this parser exists to avoid: silently misaligning columns after
    an AFP exits or a new one enters mid-file."""
    content = (
        "Valores Confirmados\n\n"
        "Fecha;ALPHA;;BETA\n"
        ";Valor Cuota;Valor Patrimonio;Valor Cuota;Valor Patrimonio\n"
        "2020-01-01;100,00;1000;200,00;2000\n"
        "2020-01-02;101,00;1010;201,00;2010\n"
        "\nValores Confirmados\n\n"
        "Fecha;ALPHA;;GAMMA\n"
        ";Valor Cuota;Valor Patrimonio;Valor Cuota;Valor Patrimonio\n"
        "2020-01-03;102,00;1020;50,00;500\n"
    )
    f = tmp_path / "fondo_test.csv"
    f.write_text(content, encoding="latin-1")

    df = parser.parse_fund_file(f, fondo="X")

    beta_rows = df.filter(df["afp"] == "BETA")
    assert beta_rows.height == 2
    assert beta_rows["valor_cuota"].to_list() == [200.0, 201.0]

    gamma_rows = df.filter(df["afp"] == "GAMMA")
    assert gamma_rows.height == 1
    assert gamma_rows["valor_cuota"].to_list() == [50.0]

    alpha_rows = df.filter(df["afp"] == "ALPHA")
    assert alpha_rows.height == 3  # present in both header blocks


def test_parse_fund_file_ignores_rows_before_any_header(tmp_path):
    content = "Valores Confirmados\n\n2020-01-01;100,00;1000\nFecha;ALPHA\n;Valor Cuota;Valor Patrimonio\n2020-01-02;101,00;1010\n"
    f = tmp_path / "fondo_test.csv"
    f.write_text(content, encoding="latin-1")

    df = parser.parse_fund_file(f, fondo="X")

    assert df.height == 1
    assert df["fecha"][0].isoformat() == "2020-01-02"
