"""KPIs: los indicadores estándar con que se evalúa un fondo, una estrategia y una pensión.

Los módulos anteriores responden preguntas puntuales con proporciones ("costó en
el 59% de las historias"). Eso no es como se evalúa nada en la industria. Un
fondo se juzga por su retorno ajustado por riesgo y por sus caídas; una
estrategia, contra su benchmark y con su tasa de acierto y su payoff; una
pensión, por su tasa de reemplazo. Este módulo calcula esos indicadores sobre
los mismos datos, para que las conclusiones se puedan comparar con cualquier
otro análisis del rubro.

Y cierra un hueco analítico real: todo lo anterior mide cuánto *retorno* cuesta
cambiarse al Fondo E, y nunca cuánto *riesgo* evita. Una regla que reduce la
caída máxima a cambio de algo de retorno no es necesariamente peor; depende de
para quién. Por eso cada estrategia se reporta con las dos columnas.

**Convenciones, declaradas de frente:**

- Todo en términos reales (índice deflactado por la UF).
- Sharpe con tres tasas libres de riesgo reales: 0%, 1% y 2%, en vez de
  esconder el supuesto en una sola cifra. Importa: el orden de los fondos
  CAMBIA con la tasa (el Fondo E pasa del tercer lugar al último entre 0% y
  1%). Lo único robusto a las tres es que el Fondo C queda primero. Una
  versión anterior de este docstring afirmaba que el orden no cambiaba; era
  falso, y la tabla de sensibilidad es la corrección. Sortino, con objetivo 0.
- Fondos: retornos diarios hábiles. Estrategias: retornos semanales, porque sus
  señales son semanales. La anualización usa los períodos por año observados
  en la serie (~261 días hábiles, porque incluye feriados), no 252 fijos.
- VaR y CVaR al 95%, sobre retornos mensuales, en positivo: "en el 5% de los
  peores meses se pierde en promedio X%".
- Las estrategias se comparan sobre la misma ventana: desde octubre de 2006,
  primera semana en que existe la señal de régimen fuera de muestra.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.bootstrap_cost import indices_bootstrap_estacionario  # noqa: E402
from analysis.pension_loss import (  # noqa: E402
    CRECIMIENTO_SALARIAL_REAL_ANUAL,
    EDAD_INICIO_COTIZACION,
    EDAD_JUBILACION,
    SALARIO_MENSUAL_UF,
)
from analysis.time_series import cargar_indice_real, probabilidad_fuera_de_muestra  # noqa: E402

DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"

SEMANAS = 52
UMBRAL_CAIDA = 0.15
SEMANAS_FUERA = 52
REZAGO = 1
N_TRAYECTORIAS = 2000
LARGO_BLOQUE = 26


# ---------------------------------------------------------------------------
# Indicadores de un camino de riqueza
# ---------------------------------------------------------------------------

TASAS_LIBRES_DE_RIESGO = (0.0, 0.01, 0.02)


def kpis_de_camino(riqueza: pd.Series, periodos_por_anio: float | None = None) -> dict:
    """KPIs estándar de un camino de riqueza (índice o estrategia).

    Si no se indica, los períodos por año se miden en la propia serie: una
    serie de días hábiles con feriados tiene ~261 por año, y anualizar con 252
    subestimaría volatilidad y retorno medio.
    """
    r = riqueza.pct_change().dropna()
    anios = (riqueza.index[-1] - riqueza.index[0]).days / 365.25
    ppa = periodos_por_anio or len(r) / anios
    cagr = (riqueza.iloc[-1] / riqueza.iloc[0]) ** (1 / anios) - 1
    vol = r.std() * np.sqrt(ppa)
    media = r.mean() * ppa
    abajo = np.sqrt((np.minimum(r, 0) ** 2).mean()) * np.sqrt(ppa)

    caida = riqueza / riqueza.cummax() - 1
    t_piso = caida.idxmin()
    antes = riqueza[:t_piso]
    t_max, v_max = antes.idxmax(), antes.max()
    despues = riqueza[t_piso:]
    recuperado = despues[despues >= v_max]
    t_rec = recuperado.index[0] if len(recuperado) else None
    fin_agua = t_rec if t_rec is not None else riqueza.index[-1]
    meses_bajo_agua = (fin_agua - t_max).days / 30.44

    mensual = riqueza.resample("ME").last().pct_change().dropna()
    q05 = mensual.quantile(0.05)
    anual_movil = riqueza.resample("ME").last().pct_change(12).dropna()

    return {
        "cagr_pct": cagr * 100,
        "volatilidad_pct": vol * 100,
        "sharpe": media / vol if vol else float("nan"),
        **{f"sharpe_rf{int(rf * 100)}": (media - rf) / vol if vol else float("nan")
           for rf in TASAS_LIBRES_DE_RIESGO if rf > 0},
        "sortino": media / abajo if abajo else float("nan"),
        "drawdown_max_pct": caida.min() * 100,
        "drawdown_max_desde": str(t_max.date()),
        "drawdown_max_piso": str(t_piso.date()),
        "drawdown_max_recuperado": str(t_rec.date()) if t_rec is not None else None,
        "meses_bajo_el_agua": meses_bajo_agua,
        "calmar": cagr / abs(caida.min()) if caida.min() else float("nan"),
        "var95_mensual_pct": -q05 * 100,
        "cvar95_mensual_pct": -mensual[mensual <= q05].mean() * 100,
        "peor_12_meses_pct": anual_movil.min() * 100,
        "pct_ventanas_12m_negativas": (anual_movil < 0).mean() * 100,
    }


# ---------------------------------------------------------------------------
# Estrategias de cambio
# ---------------------------------------------------------------------------

def mascara_de_eventos(eventos: list[int], n: int, rezago: int = REZAGO,
                       semanas_fuera: int = SEMANAS_FUERA) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Semanas en que el saldo está en el Fondo E, dados los eventos de salida.

    Un evento en la semana i ejecuta el traspaso al cierre de i + rezago y el
    saldo vuelve al Fondo A `semanas_fuera` semanas después. Un evento que ocurre
    estando ya afuera no es una nueva decisión. La semana t queda en el E si el
    traspaso de salida se ejecutó antes de su inicio y el de vuelta no.
    """
    en_e = np.zeros(n, dtype=bool)
    tramos: list[tuple[int, int]] = []
    libre_desde = 0
    for i in sorted(eventos):
        j = i + rezago
        k = j + semanas_fuera
        if j < libre_desde or k >= n:
            continue
        en_e[j + 1:k + 1] = True
        tramos.append((j, k))
        libre_desde = k
    return en_e, tramos


def eventos_regla_observable(nivel_a: np.ndarray, umbral: float = UMBRAL_CAIDA) -> list[int]:
    """Primera semana de cada caída en que la pérdida desde el máximo cruza el umbral."""
    eventos, maximo, disparada = [], nivel_a[0], False
    for t in range(1, len(nivel_a)):
        if nivel_a[t] >= maximo:
            maximo, disparada = nivel_a[t], False
        elif not disparada and nivel_a[t] / maximo - 1 <= -umbral:
            eventos.append(t)
            disparada = True
    return eventos


def eventos_regla_piso(nivel_a: np.ndarray, umbral: float = UMBRAL_CAIDA) -> list[int]:
    """Semana del mínimo de cada caída de `umbral` o más que se recuperó.

    Es la regla con retrospectiva: no se puede ejecutar en tiempo real, porque el
    mínimo solo se identifica cuando el fondo vuelve a su máximo. Se incluye
    como referencia del peor caso, nunca como estrategia.
    """
    eventos, maximo, t_min = [], nivel_a[0], 0
    for t in range(1, len(nivel_a)):
        if nivel_a[t] >= maximo:
            if nivel_a[t_min] / maximo - 1 <= -umbral:
                eventos.append(t_min)
            maximo, t_min = nivel_a[t], t
        elif nivel_a[t] < nivel_a[t_min]:
            t_min = t
    return eventos


def camino_estrategia(ret_a: np.ndarray, ret_e: np.ndarray, en_e: np.ndarray) -> np.ndarray:
    return np.cumprod(1 + np.where(en_e, ret_e, ret_a))


def estadisticas_de_decisiones(ret_a: np.ndarray, ret_e: np.ndarray,
                               tramos: list[tuple[int, int]]) -> dict:
    """Tasa de acierto y payoff de las decisiones de salir al Fondo E.

    Una decisión "acierta" si, mientras el saldo estuvo en el E, el E rindió más
    que el A. El payoff ratio compara lo que se gana en promedio cuando se
    acierta con lo que se pierde en promedio cuando no: con un payoff menor que
    1, hace falta acertar más de la mitad de las veces solo para empatar.
    """
    difs = []
    for j, k in tramos:
        ra = np.prod(1 + ret_a[j + 1:k + 1]) - 1
        re = np.prod(1 + ret_e[j + 1:k + 1]) - 1
        difs.append((re - ra) * 100)
    difs = np.array(difs)
    if len(difs) == 0:
        return {"decisiones": 0}
    gana, pierde = difs[difs > 0], -difs[difs <= 0]
    return {
        "decisiones": int(len(difs)),
        "tasa_acierto_pct": float((difs > 0).mean() * 100),
        "ganancia_media_al_acertar_pp": float(gana.mean()) if len(gana) else 0.0,
        "perdida_media_al_fallar_pp": float(pierde.mean()) if len(pierde) else 0.0,
        "payoff_ratio": float(gana.mean() / pierde.mean()) if len(gana) and len(pierde) else float("nan"),
        "valor_esperado_por_decision_pp": float(difs.mean()),
    }


def scorecard_estrategias(a: pd.Series, e: pd.Series, prob_regimen: pd.Series) -> dict:
    """KPIs de cada estrategia sobre la historia real, en una ventana común."""
    sa = a.resample("W-FRI").last()
    se = e.resample("W-FRI").last()
    df = pd.concat([sa, se], axis=1, join="inner").dropna()
    df.columns = ["A", "E"]
    nivel_a = df["A"].values
    inicio = df.index.get_indexer([prob_regimen.index[0]])[0]

    # Las señales usan toda la historia previa (el máximo corrido de 2002 en
    # adelante), pero solo cuentan las decisiones dentro de la ventana común.
    obs = [t for t in eventos_regla_observable(nivel_a) if t >= inicio]
    piso = [t for t in eventos_regla_piso(nivel_a) if t >= inicio]
    p = prob_regimen.reindex(df.index).values
    reg = [t for t in range(max(inicio, 1), len(p))
           if not np.isnan(p[t]) and not np.isnan(p[t - 1]) and p[t] > 0.5 >= p[t - 1]]

    v = df.iloc[inicio:]
    ret_a = v["A"].pct_change().fillna(0).values
    ret_e = v["E"].pct_change().fillna(0).values
    n = len(v)
    salida = {}
    for nombre, eventos, rezago in (
            ("Quedarse en A", [], REZAGO),
            ("Siempre en E", None, REZAGO),
            ("Regla −15% (observable)", obs, REZAGO),
            ("Régimen fuera de muestra", reg, REZAGO),
            ("Piso (retrospectiva, no ejecutable)", piso, 0)):
        if eventos is None:
            en_e, tramos = np.ones(n, dtype=bool), []
        else:
            en_e, tramos = mascara_de_eventos([t - inicio for t in eventos], n, rezago)
        riqueza = pd.Series(camino_estrategia(ret_a, ret_e, en_e), index=v.index)
        k = kpis_de_camino(riqueza)
        k["pct_tiempo_en_e"] = float(en_e.mean() * 100)
        k.update(estadisticas_de_decisiones(ret_a, ret_e, tramos))
        salida[nombre] = k

        # El benchmark justo de una regla que pasa una fracción w del tiempo en
        # el E no es "100% en A": es una mezcla fija con esa misma exposición
        # promedio, rebalanceada cada semana. Si la mezcla logra lo mismo, la
        # regla no aporta timing: solo baja la exposición.
        w = en_e.mean()
        if eventos and 0 < w < 1:
            mezcla = pd.Series(np.cumprod(1 + (1 - w) * ret_a + w * ret_e), index=v.index)
            km = kpis_de_camino(mezcla)
            km["pct_tiempo_en_e"] = float(w * 100)
            salida[f"Mezcla fija {100 - w * 100:.0f}% A / {w * 100:.0f}% E (benchmark de: {nombre})"] = km
    salida["_ventana"] = {"desde": str(v.index[0].date()), "hasta": str(v.index[-1].date())}
    return salida


# ---------------------------------------------------------------------------
# La regla contra quedarse, en 2.000 historias
# ---------------------------------------------------------------------------

def _cagr_vol_sharpe_dd(riqueza: np.ndarray) -> tuple[float, float, float, float]:
    r = np.diff(riqueza) / riqueza[:-1]
    anios = len(r) / SEMANAS
    cagr = (riqueza[-1] / riqueza[0]) ** (1 / anios) - 1
    vol = r.std() * np.sqrt(SEMANAS)
    sharpe = r.mean() * SEMANAS / vol
    dd = (riqueza / np.maximum.accumulate(riqueza) - 1).min()
    return cagr * 100, vol * 100, sharpe, dd * 100


def kpis_bootstrap(r_log: np.ndarray, n_trayectorias: int = N_TRAYECTORIAS,
                   largo_bloque: int = LARGO_BLOQUE, semilla: int = 42) -> dict:
    """Distribución de ΔCAGR, ΔSharpe y ΔDrawdown de cada regla frente a quedarse.

    Usa el mismo bootstrap estacionario que `bootstrap_cost.py`, pero evalúa la
    estrategia completa a lo largo de los 24 años de cada historia, no decisión
    por decisión: es la comparación que haría un comité de inversiones.
    """
    rng = np.random.default_rng(semilla)
    n = len(r_log)
    filas = []
    for _ in range(n_trayectorias):
        idx = indices_bootstrap_estacionario(n, largo_bloque, rng)
        ra_log, re_log = r_log[idx, 0], r_log[idx, 1]
        nivel_a = np.exp(np.concatenate([[0.0], np.cumsum(ra_log)]))
        ret_a = np.concatenate([[0.0], np.expm1(ra_log)])
        ret_e = np.concatenate([[0.0], np.expm1(re_log)])
        base = _cagr_vol_sharpe_dd(np.cumprod(1 + ret_a))
        fila = {}
        for nombre, eventos, rezago in (
                ("observable", eventos_regla_observable(nivel_a), REZAGO),
                ("piso", eventos_regla_piso(nivel_a), 0)):
            en_e, _ = mascara_de_eventos(eventos, len(ret_a), rezago)
            k = _cagr_vol_sharpe_dd(camino_estrategia(ret_a, ret_e, en_e))
            fila[f"{nombre}_dcagr"] = k[0] - base[0]
            fila[f"{nombre}_dvol"] = k[1] - base[1]
            fila[f"{nombre}_dsharpe"] = k[2] - base[2]
            fila[f"{nombre}_ddd"] = k[3] - base[3]     # positivo = caída máxima más chica
            # Valor de timing: la regla contra una mezcla fija con su misma
            # exposición promedio al E en ESA historia.
            w = en_e.mean()
            m = _cagr_vol_sharpe_dd(np.cumprod(1 + (1 - w) * ret_a + w * ret_e))
            fila[f"{nombre}_timing_dcagr"] = k[0] - m[0]
            fila[f"{nombre}_timing_dsharpe"] = k[2] - m[2]
            fila[f"{nombre}_timing_ddd"] = k[3] - m[3]
            fila[f"{nombre}_pct_en_e"] = w * 100
        filas.append(fila)
    df = pd.DataFrame(filas)

    def resumen(col: str) -> dict:
        x = df[col]
        return {"media": float(x.mean()), "mediana": float(x.median()),
                "p05": float(x.quantile(0.05)), "p95": float(x.quantile(0.95)),
                "pct_positivo": float((x > 0).mean() * 100)}

    salida = {regla: {m: resumen(f"{regla}_{m}")
                      for m in ("dcagr", "dvol", "dsharpe", "ddd", "timing_dcagr",
                                "timing_dsharpe", "timing_ddd", "pct_en_e")}
              for regla in ("observable", "piso")}
    df.to_csv(REPORTS_DIR / "kpis_bootstrap.csv", index=False)
    return salida


# ---------------------------------------------------------------------------
# Pensión: tasa de reemplazo
# ---------------------------------------------------------------------------

def sueldo_final_uf() -> float:
    """Sueldo a los 65 en el modelo de `pension_loss.py` (un reajuste por año cumplido)."""
    anios = EDAD_JUBILACION - EDAD_INICIO_COTIZACION
    return SALARIO_MENSUAL_UF * (1 + CRECIMIENTO_SALARIAL_REAL_ANUAL) ** anios


def kpis_pension(uf_hoy: float) -> list[dict]:
    """Tasa de reemplazo y pérdida en UF y pesos, desde reports/pension_loss.csv.

    La tasa de reemplazo es pensión / último sueldo, el indicador con que la
    OCDE y la Superintendencia comparan sistemas de pensiones. En este modelo
    se cotiza todos los meses, así que su NIVEL es un techo: con una densidad de
    cotización d, la tasa es d veces la reportada. La pérdida PORCENTUAL no
    cambia con la densidad si las lagunas se reparten parejo.
    """
    df = pd.read_csv(REPORTS_DIR / "pension_loss.csv")
    sueldo = sueldo_final_uf()
    filas = []
    for _, r in df.iterrows():
        tr_q = r.pension_quedarse_uf / sueldo * 100
        tr_p = r.pension_panico_uf / sueldo * 100
        filas.append({
            "evento": r.evento, "regla": r.regla, "edad": int(r.edad_al_evento),
            "pension_quedarse_uf": r.pension_quedarse_uf,
            "pension_cambio_uf": r.pension_panico_uf,
            "cambio_pension_uf_mes": r.pension_panico_uf - r.pension_quedarse_uf,
            "cambio_pension_clp_mes": (r.pension_panico_uf - r.pension_quedarse_uf) * uf_hoy,
            "cambio_saldo_clp": (r.saldo_panico_uf - r.saldo_quedarse_uf) * uf_hoy,
            "tasa_reemplazo_quedarse_pct": tr_q,
            "tasa_reemplazo_cambio_pct": tr_p,
            "cambio_tasa_reemplazo_pp": tr_p - tr_q,
            "cambio_pension_pct": -r.perdida_pct,
        })
    return filas


# ---------------------------------------------------------------------------

def main() -> None:
    import warnings
    warnings.simplefilter("ignore")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    indices = {f: cargar_indice_real(con, f) for f in "ABCDE"}
    uf_hoy = con.execute("SELECT uf FROM uf_daily ORDER BY fecha DESC LIMIT 1").fetchone()[0]
    con.close()

    resultado: dict = {}

    print("1. FONDOS (real, UF; diarios hábiles)")
    fondos = {}
    for f, s in indices.items():
        habil = s[s.index.dayofweek < 5]
        fondos[f] = kpis_de_camino(habil)
    resultado["fondos"] = fondos
    cab = (f"   {'':8}{'CAGR':>7}{'Vol':>7}{'Sh rf0':>8}{'Sh rf1':>8}{'Sh rf2':>8}{'Sortino':>8}"
           f"{'MaxDD':>8}{'Meses agua':>11}{'Calmar':>8}{'CVaR95 m':>10}{'Peor 12m':>10}")
    print(cab)
    for f, k in fondos.items():
        print(f"   Fondo {f}{k['cagr_pct']:>6.2f}%{k['volatilidad_pct']:>6.1f}%"
              f"{k['sharpe']:>8.2f}{k['sharpe_rf1']:>8.2f}{k['sharpe_rf2']:>8.2f}"
              f"{k['sortino']:>8.2f}{k['drawdown_max_pct']:>7.1f}%"
              f"{k['meses_bajo_el_agua']:>11.0f}{k['calmar']:>8.2f}"
              f"{k['cvar95_mensual_pct']:>9.1f}%{k['peor_12_meses_pct']:>9.1f}%")
    for rf, col in ((0, "sharpe"), (1, "sharpe_rf1"), (2, "sharpe_rf2")):
        orden = sorted(fondos, key=lambda f: -fondos[f][col])
        print(f"   orden por Sharpe con tasa real {rf}%: {' > '.join(orden)}")
    print()

    print("2. ESTRATEGIAS sobre la historia real (semanales, ventana común)")
    prob = probabilidad_fuera_de_muestra(indices["A"])
    est = scorecard_estrategias(indices["A"], indices["E"], prob)
    resultado["estrategias"] = est
    print(f"   ventana {est['_ventana']['desde']} -> {est['_ventana']['hasta']}")
    print(f"   {'':38}{'CAGR':>7}{'Vol':>7}{'Sharpe':>8}{'MaxDD':>8}{'Calmar':>8}"
          f"{'%en E':>7}{'Dec.':>5}{'Acierto':>8}{'Payoff':>8}")
    for nombre, k in est.items():
        if nombre.startswith("_"):
            continue
        dec = k.get("decisiones", 0)
        acierto = f"{k['tasa_acierto_pct']:.0f}%" if dec else "—"
        payoff = f"{k['payoff_ratio']:.2f}" if dec and not np.isnan(k.get("payoff_ratio", np.nan)) else "—"
        print(f"   {nombre:<38}{k['cagr_pct']:>6.2f}%{k['volatilidad_pct']:>6.1f}%"
              f"{k['sharpe']:>8.2f}{k['drawdown_max_pct']:>7.1f}%{k['calmar']:>8.2f}"
              f"{k['pct_tiempo_en_e']:>6.0f}%{dec:>5}{acierto:>8}{payoff:>8}")
    print()

    print(f"3. LA REGLA CONTRA QUEDARSE, en {N_TRAYECTORIAS:,} historias (bloque {LARGO_BLOQUE} sem.)")
    from analysis.bootstrap_cost import retornos_semanales_conjuntos
    con = duckdb.connect(str(DB_PATH), read_only=True)
    r_log = retornos_semanales_conjuntos(con)
    con.close()
    boot = kpis_bootstrap(r_log)
    resultado["bootstrap"] = boot
    nombres = {"dcagr": "ΔCAGR vs A (pp/año)", "dvol": "ΔVolatilidad vs A (pp)",
               "dsharpe": "ΔSharpe vs A", "ddd": "ΔCaída máx. vs A (pp, + = menor)",
               "timing_dcagr": "ΔCAGR vs mezcla fija", "timing_dsharpe": "ΔSharpe vs mezcla fija",
               "timing_ddd": "ΔCaída máx. vs mezcla fija", "pct_en_e": "% del tiempo en E"}
    for regla, etiqueta in (("observable", "Regla −15% (observable)"),
                            ("piso", "Piso (retrospectiva)")):
        print(f"   {etiqueta}")
        for m, txt in nombres.items():
            x = boot[regla][m]
            print(f"     {txt:<32} media {x['media']:+7.2f}   IC90 [{x['p05']:+7.2f}, {x['p95']:+7.2f}]"
                  f"   > 0 en {x['pct_positivo']:>3.0f}%")
    print()

    print("4. PENSIÓN: tasa de reemplazo (cotización continua; con densidad d, multiplicar por d)")
    pen = kpis_pension(uf_hoy)
    resultado["pension"] = pen
    resultado["pension_supuestos"] = {"sueldo_final_uf": sueldo_final_uf(), "uf_hoy": uf_hoy}
    print(f"   sueldo final {sueldo_final_uf():.2f} UF; pesos a UF {uf_hoy:,.2f}")
    print(f"   {'evento':<18}{'regla':<11}{'edad':>5}{'TR quedarse':>12}{'TR cambio':>10}"
          f"{'Δ TR':>8}{'Δ UF/mes':>10}{'Δ $/mes':>11}")
    for x in pen:
        if x["edad"] in (30, 50):
            print(f"   {x['evento']:<18}{x['regla']:<11}{x['edad']:>5}"
                  f"{x['tasa_reemplazo_quedarse_pct']:>11.1f}%{x['tasa_reemplazo_cambio_pct']:>9.1f}%"
                  f"{x['cambio_tasa_reemplazo_pp']:>+7.1f}{x['cambio_pension_uf_mes']:>+10.2f}"
                  f"{x['cambio_pension_clp_mes']:>+11,.0f}")

    pd.DataFrame(fondos).T.to_csv(REPORTS_DIR / "kpis_fondos.csv")
    pd.DataFrame({k: v for k, v in est.items() if not k.startswith("_")}).T.to_csv(
        REPORTS_DIR / "kpis_estrategias.csv")
    pd.DataFrame(pen).to_csv(REPORTS_DIR / "kpis_pension.csv", index=False)
    (REPORTS_DIR / "kpis.json").write_text(
        json.dumps(resultado, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print("\n-> reports/kpis.json, kpis_fondos.csv, kpis_estrategias.csv, kpis_bootstrap.csv, "
          "kpis_pension.csv")


if __name__ == "__main__":
    main()
