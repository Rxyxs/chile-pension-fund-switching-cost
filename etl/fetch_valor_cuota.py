"""Download the real daily valor-cuota history (2002-current) for each multifondo (A-E)
from the Superintendencia de Pensiones' public export endpoint.

No API key, no auth — this is the same endpoint the "Genera archivo" button on
https://www.spensiones.cl/apps/valoresCuotaFondo/vcfAFP.php calls from the browser.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
FUND_TYPES = ["A", "B", "C", "D", "E"]
BASE_URL = "https://www.spensiones.cl/apps/valoresCuotaFondo/vcfAFPxls.php"


def fetch_fund(fondo: str, year_from: int = 2002, year_to: int | None = None) -> str:
    year_to = year_to or date.today().year
    params = {
        "aaaaini": year_from,
        "aaaafin": year_to,
        "tf": fondo,
        "fecconf": date.today().strftime("%Y%m%d"),
    }
    resp = requests.get(BASE_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.content.decode("latin-1")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for fondo in FUND_TYPES:
        text = fetch_fund(fondo)
        out_path = RAW_DIR / f"valor_cuota_fondo_{fondo}.csv"
        out_path.write_text(text, encoding="latin-1")
        n_lines = text.count("\n")
        print(f"fondo {fondo}: {n_lines:,} lineas -> {out_path.relative_to(RAW_DIR.parents[1])}")


if __name__ == "__main__":
    main()
