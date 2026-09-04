"""Parse Tabla N 7 of each "Ficha Estadistica Previsional" PDF: the real, system-wide count
of accounts transferred between AFPs that month.

A real data-quality trap this parser exists to work around: footnote (3) under Tabla N 7
states the month in prose ("...traspasadas entre AFP en agosto de 2020 fue de...") and in
at least two of the 22 bulletins checked here, that prose month is simply wrong -- it names
the month the table covered a year or a month earlier, not the one the table's own column
headers say. The table's header row (e.g. "(Sep 20)") is authoritative -- it's what every
other column on the same table is dated by -- so this parser derives the month from the
header instead of trusting the footnote's prose, and only takes the transfer count itself
from the footnote (that number checks out against the table's own "Total" row context).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "fichas"

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

TOTAL_RE = re.compile(
    r"traspasadas entre AFP en [\wáéíóúñ]+\.?\s*(?:de\s*)?\d{4} fue de ([\d.]+)",
    re.IGNORECASE,
)
HEADER_TOKEN_RE = re.compile(r"\((\w{3})\.?\s?(\d{2,4})\)")


def _normalize_year(year_str: str) -> int:
    return int(year_str) if len(year_str) == 4 else 2000 + int(year_str)


def parse_tabla7_text(text: str) -> tuple[str | None, int | None]:
    """Returns (data_month as 'YYYY-MM', total_transfers) parsed from a Tabla N 7 page's text."""
    total_match = TOTAL_RE.search(text)
    total = int(total_match.group(1).rstrip(".").replace(".", "")) if total_match else None

    header_line = next(
        (line for line in text.splitlines() if line.count("(") >= 4 and HEADER_TOKEN_RE.search(line)),
        None,
    )
    data_month = None
    if header_line:
        tokens = HEADER_TOKEN_RE.findall(header_line)
        if tokens:
            # The period appears 3 times among the 4 single-month parens (participacion
            # afiliados, traspasos, ingreso promedio all share one month; only
            # "participacion activos" is one month ahead) -- the mode picks it robustly.
            month_abbrev, year_str = Counter(tokens).most_common(1)[0][0]
            month_num = MESES.get(month_abbrev.lower())
            if month_num:
                data_month = f"{_normalize_year(year_str):04d}-{month_num:02d}"

    return data_month, total


def parse_all_fichas() -> list[dict]:
    rows = []
    for path in sorted(RAW_DIR.glob("*.pdf")):
        with pdfplumber.open(path) as pdf:
            text = pdf.pages[2].extract_text() or ""
        data_month, total = parse_tabla7_text(text)
        if data_month is None or total is None:
            raise ValueError(f"could not parse {path.name}: data_month={data_month} total={total}")
        rows.append({"ficha": path.stem, "data_month": data_month, "total_traspasos": total})
    return rows


if __name__ == "__main__":
    import polars as pl

    rows = parse_all_fichas()
    df = pl.DataFrame(rows).sort("data_month")
    print(df)

    out_path = RAW_DIR.parents[1] / "processed" / "traspasos_monthly.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out_path)
    print(f"-> {out_path.relative_to(RAW_DIR.parents[2])}")
