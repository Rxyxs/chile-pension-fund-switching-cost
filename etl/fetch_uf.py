"""Download the daily Unidad de Fomento (UF) history, 2002-current.

Why this exists: every valor cuota in this repository is in nominal pesos, so every
return computed from it carries Chilean inflation inside it -- roughly a third of
Fondo A's ~9.5% nominal annual return. That is harmless when comparing two funds
over the same days (inflation cancels out of the ratio), but it breaks any analysis
that mixes fund returns with salaries, contributions or pensions, which is what
`analysis/pension_loss.py` does. Chilean pensions are denominated in UF precisely
for this reason, so the analysis is done in UF too.

Source: mindicador.cl, a public mirror of the Banco Central de Chile series. No key,
no auth. One request per year. Spot-checked against the SII's published UF table
(31-Dec-2008 = 21,452.57) -- see `tests/test_uf.py`.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT_PATH = RAW_DIR / "uf_daily.json"
BASE_URL = "https://mindicador.cl/api/uf/{year}"


def fetch_year(year: int) -> list[dict]:
    resp = requests.get(BASE_URL.format(year=year), timeout=60)
    resp.raise_for_status()
    serie = resp.json()["serie"]
    # The API returns newest-first with full ISO timestamps; keep just the date.
    return [{"fecha": s["fecha"][:10], "uf": float(s["valor"])} for s in serie]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for year in range(2002, date.today().year + 1):
        year_rows = fetch_year(year)
        rows.extend(year_rows)
        print(f"{year}: {len(year_rows)} dias")
        time.sleep(0.5)  # a public, free mirror: no reason to hammer it

    rows.sort(key=lambda r: r["fecha"])
    OUT_PATH.write_text(json.dumps(rows), encoding="utf-8")
    print(f"-> {OUT_PATH.relative_to(RAW_DIR.parents[1])} ({len(rows):,} dias)")


if __name__ == "__main__":
    main()
