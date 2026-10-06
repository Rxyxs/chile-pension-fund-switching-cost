"""Inferencia sobre el costo del pánico: de 3 episodios a miles.

El resultado central del proyecto -- "en los 15 escenarios, quedarse ganó" -- se
apoya en 3 caídas reales. El propio README lo admite: la muestra efectiva se
parece más a 3 que a 15. Este módulo ataca esa debilidad y otra más seria que el
proyecto no había nombrado.

**La debilidad no nombrada: el piso es retrospectivo.** "Cambiarse en el piso"
usa el mínimo *realizado* de la caída, y el mínimo realizado garantiza por
construcción que lo que viene después es una subida. Nadie sabe que está en el
piso: eso se sabe después. Así que parte del costo medido podría ser un
artefacto de haber elegido, con el diario de mañana, el peor día posible para
moverse. Además, `drawdown_episodes.py` solo considera caídas que *se
recuperaron*: una caída que nunca vuelve no entra, y justo esas son las que
harían ganar al que se cambió (sesgo de supervivencia).

Así que se comparan dos reglas de pánico:

- **piso** (retrospectiva): la del proyecto. Cambio en el mínimo de cada caída de
  15% o más que se recuperó.
- **observable**: cambio la primera semana en que la pérdida desde el último
  máximo cruza un umbral, con una semana de rezago de ejecución, en *toda*
  caída que lo cruce -- se recupere o no. Es lo que una persona podría hacer de
  verdad.

**Cómo se generan miles de historias.** Bootstrap estacionario (Politis y Romano,
1994) sobre los retornos semanales reales de A y E. Se remuestrean *bloques* de
semanas consecutivas, no semanas sueltas, para conservar lo que hace a una crisis
una crisis: el agrupamiento de la volatilidad y la dinámica de caída y rebote.
Los dos fondos se remuestrean con los mismos índices, para conservar su
correlación. El largo medio del bloque es el parámetro delicado -- bloques cortos
rompen las recuperaciones en V, que son justamente el mecanismo del costo -- así
que se reporta con tres largos distintos.

Lo que esto NO resuelve: el bootstrap solo recombina la historia observada. Si
2002-2026 no contiene cierto tipo de crisis, ninguna remuestra la va a producir.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.time_series import cargar_indice_real  # noqa: E402

DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"

UMBRAL_CAIDA = 0.15            # el mismo 15% de drawdown_episodes.py
SEMANAS_FUERA = 52
REZAGO_EJECUCION = 1
N_TRAYECTORIAS = 2000
LARGOS_BLOQUE = (13, 26, 52)   # semanas: un trimestre, un semestre, un año
BLOQUE_PARA_GRAFICO = 26


def retornos_semanales_conjuntos(con: duckdb.DuckDBPyConnection) -> np.ndarray:
    """Matriz (semanas × 2) de retornos log semanales reales de A y E."""
    a = cargar_indice_real(con, "A").resample("W-FRI").last()
    e = cargar_indice_real(con, "E").resample("W-FRI").last()
    df = pd.concat([a, e], axis=1, join="inner").dropna()
    return np.diff(np.log(df.values), axis=0)


def indices_bootstrap_estacionario(n: int, largo_medio: float,
                                   rng: np.random.Generator) -> np.ndarray:
    """Índices de una remuestra de largo `n` con bloques de largo geométrico.

    Cada paso continúa el bloque actual con probabilidad 1 - 1/largo_medio, o
    salta a una posición al azar. Es circular: al pasar el final se vuelve al
    principio, para que las últimas semanas no tengan menos chance de aparecer.
    """
    saltos = rng.random(n) < 1.0 / largo_medio
    destinos = rng.integers(0, n, size=n)
    idx = np.empty(n, dtype=np.int64)
    idx[0] = destinos[0]
    for t in range(1, n):
        idx[t] = destinos[t] if saltos[t] else (idx[t - 1] + 1) % n
    return idx


@dataclass(frozen=True)
class Decision:
    regla: str
    caida_al_cambiarse: float     # pérdida desde el máximo en la semana del cambio
    costo_pp: float               # retorno de A menos retorno de E, en las semanas fuera


def decisiones_en_trayectoria(r_a: np.ndarray, r_e: np.ndarray,
                              umbral: float = UMBRAL_CAIDA,
                              semanas_fuera: int = SEMANAS_FUERA,
                              rezago: int = REZAGO_EJECUCION) -> list[Decision]:
    """Aplica las dos reglas de pánico sobre una trayectoria de retornos log."""
    nivel_a = np.concatenate([[0.0], np.cumsum(r_a)])
    nivel_e = np.concatenate([[0.0], np.cumsum(r_e)])
    n = len(nivel_a)
    salida: list[Decision] = []

    def costo(t0: int) -> float | None:
        t1 = t0 + semanas_fuera
        if t1 >= n:
            return None
        ra = np.exp(nivel_a[t1] - nivel_a[t0]) - 1
        re = np.exp(nivel_e[t1] - nivel_e[t0]) - 1
        return (ra - re) * 100

    maximo = nivel_a[0]
    t_min = 0                              # mínimo desde el último máximo
    disparada = False                      # ¿la regla observable ya actuó en esta caída?
    for t in range(1, n):
        if nivel_a[t] >= maximo:
            # Nuevo máximo: si hubo una caída de 15%+ desde el anterior, esa caída
            # se recuperó y su mínimo es el "piso" de la regla retrospectiva.
            caida_max = 1 - np.exp(nivel_a[t_min] - maximo)
            if caida_max >= umbral:
                c = costo(t_min)
                if c is not None:
                    salida.append(Decision("piso", -caida_max * 100, c))
            maximo, t_min, disparada = nivel_a[t], t, False
            continue
        if nivel_a[t] < nivel_a[t_min]:
            t_min = t
        caida = 1 - np.exp(nivel_a[t] - maximo)
        if not disparada and caida >= umbral:
            disparada = True
            c = costo(t + rezago)
            if c is not None:
                salida.append(Decision("observable", -caida * 100, c))
    return salida


def resumir(costos: np.ndarray) -> dict:
    if len(costos) == 0:
        return {"n": 0}
    return {
        "n": int(len(costos)),
        "media_pp": float(np.mean(costos)),
        "mediana_pp": float(np.median(costos)),
        "p05_pp": float(np.percentile(costos, 5)),
        "p95_pp": float(np.percentile(costos, 95)),
        "prob_salir_cuesta": float(np.mean(costos > 0) * 100),
    }


def correr(r: np.ndarray, largo_bloque: int, n_trayectorias: int,
           semilla: int) -> tuple[dict, dict[str, list[float]]]:
    rng = np.random.default_rng(semilla)
    n = len(r)
    por_regla: dict[str, list[float]] = {"piso": [], "observable": []}
    medias_por_trayectoria: dict[str, list[float]] = {"piso": [], "observable": []}
    for _ in range(n_trayectorias):
        idx = indices_bootstrap_estacionario(n, largo_bloque, rng)
        decs = decisiones_en_trayectoria(r[idx, 0], r[idx, 1])
        for regla in por_regla:
            cs = [d.costo_pp for d in decs if d.regla == regla]
            por_regla[regla].extend(cs)
            if cs:
                medias_por_trayectoria[regla].append(float(np.mean(cs)))
    salida = {}
    for regla, cs in por_regla.items():
        res = resumir(np.array(cs))
        m = np.array(medias_por_trayectoria[regla])
        if len(m):
            # Intervalo para el costo MEDIO de una historia de 24 años: es la
            # incertidumbre sobre el número que reporta el README.
            res["media_por_historia_ic90"] = [float(np.percentile(m, 5)),
                                              float(np.percentile(m, 95))]
        salida[regla] = res
    return salida, por_regla


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    r = retornos_semanales_conjuntos(con)
    con.close()

    historico = decisiones_en_trayectoria(r[:, 0], r[:, 1])
    print("Costo del pánico: regla retrospectiva vs. regla observable")
    print(f"  {len(r):,} semanas reales; cambio a E por {SEMANAS_FUERA} semanas; "
          f"umbral de caída {UMBRAL_CAIDA:.0%}")
    print()
    print("  En la historia real:")
    for regla in ("piso", "observable"):
        cs = [d for d in historico if d.regla == regla]
        detalle = ", ".join(f"{d.caida_al_cambiarse:.0f}% -> {d.costo_pp:+.1f} pp" for d in cs)
        print(f"    {regla:<11} {len(cs)} decisiones: {detalle}")
    print()

    resultados = {"historico": [d.__dict__ for d in historico], "bootstrap": {}}
    print(f"  En {N_TRAYECTORIAS:,} historias sintéticas de 24 años (bootstrap estacionario):")
    print(f"  {'bloque':>7} {'regla':<11} {'decisiones':>10} {'costo medio':>12} "
          f"{'mediana':>9} {'P(salir cuesta)':>16} {'IC90 media/historia':>22}")
    for L in LARGOS_BLOQUE:
        res, crudos = correr(r, L, N_TRAYECTORIAS, semilla=42 + L)
        resultados["bootstrap"][f"bloque_{L}"] = res
        if L == BLOQUE_PARA_GRAFICO:
            pd.DataFrame([{"regla": k, "costo_pp": v} for k, vs in crudos.items()
                          for v in vs]).to_csv(REPORTS_DIR / "bootstrap_decisiones.csv",
                                               index=False)
        for regla in ("piso", "observable"):
            x = res[regla]
            ic = x.get("media_por_historia_ic90", [float("nan")] * 2)
            print(f"  {L:>5} s {regla:<11} {x['n']:>10,} {x['media_pp']:>+11.1f}pp "
                  f"{x['mediana_pp']:>+8.1f}pp {x['prob_salir_cuesta']:>15.0f}% "
                  f"   [{ic[0]:+6.1f}, {ic[1]:+6.1f}] pp")
    out = REPORTS_DIR / "bootstrap_cost.json"
    out.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
