"""Download the Superintendencia de Pensiones' monthly "Ficha Estadistica Previsional"
PDF bulletins that cover the COVID crash (2019-06 to 2020-12 real switch data) and the
2022 rate-hike crisis (2022-06 to 2022-12 real switch data). Each bulletin reports, with a
2-month publication lag, the real number of accounts transferred between AFPs system-wide
that month (Tabla N 7, footnote 3) -- this is the real-behavior counterpart to the
price-only panic_switch_cost.py simulation.
"""
from __future__ import annotations

from pathlib import Path

import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "fichas"
BASE_URL = "https://www.spensiones.cl/portal/institucional/594/articles-{id}_recurso_1.pdf"

# ficha_label -> (article_id, nominal month) -- nominal month lags the reported data by ~2 months.
FICHAS = {
    "N81_ago2019": "13711",
    "N82_sep2019": "13730",
    "N83_oct2019": "13763",
    "N88_mar2020": "13888",
    "N89_abr2020": "13920",
    "N90_may2020": "13968",
    "N91_jun2020": "13985",
    "N92_jul2020": "14024",
    "N93_ago2020": "14144",
    "N94_sep2020": "14162",
    "N95_oct2020": "14199",
    "N96_nov2020": "14246",
    "N97_dic2020": "14293",
    "N98_ene2021": "14341",
    "N99_feb2021": "14393",
    "N117_ago2022": "15367",
    "N118_sep2022": "15392",
    "N119_oct2022": "15421",
    "N120_nov2022": "15439",
    "N121_dic2022": "15472",
    "N122_ene2023": "15497",
    "N123_feb2023": "15523",
}


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for label, article_id in FICHAS.items():
        url = BASE_URL.format(id=article_id)
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        out_path = RAW_DIR / f"{label}.pdf"
        out_path.write_bytes(resp.content)
        print(f"{label}: {len(resp.content):,} bytes -> {out_path.relative_to(RAW_DIR.parents[1])}")


if __name__ == "__main__":
    main()
