"""Las cifras de KPIs de los README tienen que ser las que produce el pipeline.

`reports/kpis.json` está versionado, así que este test corre en CI sin datos. Si
alguien vuelve a correr `analysis/kpis.py` con datos nuevos y no actualiza los
README, falla: un documento con cifras que el código ya no produce es peor que
uno sin cifras.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KPIS = ROOT / "reports" / "kpis.json"


def _fmt(x: float, decimales: int, coma: bool, signo: bool = False) -> str:
    s = f"{x:+.{decimales}f}" if signo else f"{x:.{decimales}f}"
    s = s.replace("-", "−")
    return s.replace(".", ",") if coma else s


@pytest.fixture(scope="module")
def kpis():
    if not KPIS.exists():
        pytest.skip("reports/kpis.json no existe (correr analysis/kpis.py)")
    return json.loads(KPIS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("archivo,coma", [("README.es.md", True), ("README.md", False)])
def test_kpis_de_fondos_aparecen_en_el_readme(kpis, archivo, coma):
    texto = (ROOT / archivo).read_text(encoding="utf-8")
    for fondo, k in kpis["fondos"].items():
        fila = next(l for l in texto.splitlines() if l.startswith(f"| {fondo} |"))
        for valor in (_fmt(k["cagr_pct"], 2, coma) + "%",
                      _fmt(k["volatilidad_pct"], 1, coma) + "%",
                      _fmt(k["sharpe"], 2, coma),
                      _fmt(k["sortino"], 2, coma),
                      _fmt(k["drawdown_max_pct"], 1, coma) + "%",
                      _fmt(k["cvar95_mensual_pct"], 1, coma) + "%"):
            assert valor in fila, f"{archivo}, fondo {fondo}: falta {valor}"


@pytest.mark.parametrize("archivo,coma", [("README.es.md", True), ("README.md", False)])
def test_kpis_de_estrategias_y_bootstrap_aparecen_en_el_readme(kpis, archivo, coma):
    texto = (ROOT / archivo).read_text(encoding="utf-8")
    est = kpis["estrategias"]
    for clave in ("Quedarse en A", "Regla −15% (observable)", "Régimen fuera de muestra"):
        assert _fmt(est[clave]["cagr_pct"], 2, coma) + "%" in texto, f"{archivo}: CAGR de {clave}"
        assert _fmt(est[clave]["drawdown_max_pct"], 1, coma) + "%" in texto, f"{archivo}: DD de {clave}"
    piso = kpis["bootstrap"]["piso"]["dcagr"]
    assert _fmt(piso["media"], 2, coma, signo=True) in texto
    assert _fmt(piso["p05"], 2, coma, signo=True) in texto
    obs = kpis["bootstrap"]["observable"]["timing_dsharpe"]
    assert _fmt(obs["media"], 2, coma, signo=True) in texto
