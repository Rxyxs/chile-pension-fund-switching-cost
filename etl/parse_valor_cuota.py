"""Parse the Superintendencia de Pensiones' raw valor-cuota exports into a tidy long table.

Source: https://www.spensiones.cl/apps/valoresCuotaFondo/vcfAFPxls.php (per fund type A-E,
2002-2026). Despite the .xls extension these are semicolon-delimited text files. The header
row repeats every time the set of active AFPs changes (mergers, exits, new entrants), so a
naive single-header read silently misaligns columns after the first change. This parser
re-reads the header at every occurrence and re-anchors column positions from it.
"""
from __future__ import annotations

import re
from pathlib import Path

import polars as pl

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
FUND_TYPES = ["A", "B", "C", "D", "E"]


def _parse_clp_number(raw: str) -> float | None:
    """'96.092,23' -> 96092.23 (CLP uses '.' as thousands separator, ',' as decimal)."""
    raw = raw.strip()
    if not raw:
        return None
    return float(raw.replace(".", "").replace(",", "."))


def parse_fund_file(path: Path, fondo: str) -> pl.DataFrame:
    lines = path.read_text(encoding="latin-1").splitlines()

    rows: list[dict] = []
    current_afps: list[str] | None = None

    for line in lines:
        if line.startswith("Fecha;"):
            current_afps = [afp for afp in line.split(";")[1:] if afp]
            continue
        if not line or not re.match(r"^\d{4}-\d{2}-\d{2};", line):
            continue
        if current_afps is None:
            continue

        fields = line.split(";")
        fecha = fields[0]
        values = fields[1:]

        for i, afp in enumerate(current_afps):
            cuota_raw = values[2 * i] if 2 * i < len(values) else ""
            patrimonio_raw = values[2 * i + 1] if 2 * i + 1 < len(values) else ""
            valor_cuota = _parse_clp_number(cuota_raw)
            valor_patrimonio = _parse_clp_number(patrimonio_raw)
            if valor_cuota is None:
                continue
            rows.append(
                {
                    "fecha": fecha,
                    "fondo": fondo,
                    "afp": afp,
                    "valor_cuota": valor_cuota,
                    "valor_patrimonio": valor_patrimonio or 0.0,
                }
            )

    df = pl.DataFrame(rows)
    return df.with_columns(pl.col("fecha").str.to_date())


def parse_all_funds() -> pl.DataFrame:
    frames = []
    for fondo in FUND_TYPES:
        path = RAW_DIR / f"valor_cuota_fondo_{fondo}.csv"
        frames.append(parse_fund_file(path, fondo))
    return pl.concat(frames).sort(["fondo", "afp", "fecha"])


if __name__ == "__main__":
    df = parse_all_funds()
    print(f"{df.height:,} filas parseadas")
    print(df.group_by("fondo").len().sort("fondo"))
    out_path = RAW_DIR.parent / "processed" / "valor_cuota_long.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out_path)
    print(f"-> {out_path.relative_to(RAW_DIR.parents[1])}")
