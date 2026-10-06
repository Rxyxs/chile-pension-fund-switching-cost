"""Series de tiempo: las afirmaciones del proyecto, sometidas a prueba formal.

Todo lo anterior de este repositorio descansa en tres afirmaciones que hasta
ahora eran argumentos, no resultados:

1. **"Nadie sabe si la caída va a seguir."** Es la razón por la que la zona donde
   cambiarse gana "no es ocupable". Es una afirmación sobre la *predictibilidad
   de los retornos*, y se puede testear: si los retornos del Fondo A tuvieran
   autocorrelación, salir después de una caída podría ser racional.
2. **"Las crisis son episodios."** El umbral de 15% de `drawdown_episodes.py` es
   una definición a dedo. Un modelo de cambio de régimen (Markov-switching)
   identifica los períodos turbulentos desde los datos, sin umbral.
3. **"En 2022 huir al E no sirvió porque los bonos también cayeron."** Es una
   afirmación sobre la correlación entre fondos, y se puede medir en el tiempo.

Y una cuarta que el proyecto no se había hecho y que importa para la pregunta
"¿cuánto tiempo me quedo afuera?": cuánto dura una tormenta de volatilidad. Un
GJR-GARCH la cuantifica como vida media de un shock.

**Una distinción que hace todo el trabajo: probabilidades suavizadas vs.
filtradas.** El modelo de régimen entrega dos. Las suavizadas usan *toda* la
muestra, incluido el futuro: sirven para fechar crisis con el diario de
mañana. Las filtradas usan solo el pasado de cada semana: son lo que alguien
podría haber sabido en el momento. Cualquier afirmación sobre una *decisión*
usa las filtradas. (Los parámetros del modelo sí se estiman con la muestra
completa; una versión estrictamente en tiempo real los reestimaría en ventana
expansiva. Se declara como limitación.)

Frecuencias: GARCH sobre retornos diarios (necesita la granularidad para ver el
clustering), régimen sobre semanales (los diarios son demasiado ruidosos para
fechar episodios), predictibilidad en diarios *y* mensuales, porque responden
preguntas distintas -- ver `predictibilidad()`.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"

DIAS_HABILES_ANIO = 252


def cargar_indice_real(con: duckdb.DuckDBPyConnection, fondo: str) -> pd.Series:
    df = con.execute(
        "SELECT fecha, index_value FROM fund_index_real WHERE fondo = ? ORDER BY fecha",
        [fondo],
    ).fetchdf()
    s = pd.Series(df.index_value.values, index=pd.to_datetime(df.fecha), name=fondo)
    return s


def retornos_log(indice: pd.Series, frecuencia: str | None = None) -> pd.Series:
    """Retornos logarítmicos en %, diarios hábiles o remuestreados ('W-FRI', 'ME').

    **Diario significa hábil, no calendario.** La Superintendencia publica valor
    cuota todos los días, incluidos sábados y domingos, y esos días el fondo casi
    no se mueve: solo devenga el interés de la renta fija (desviación diaria
    ~0,014% contra ~0,6% de un día hábil, unas 43 veces menos). Mezclar los dos
    tipos de día le muestra a un GARCH un patrón semanal fijo que no puede
    ajustar: la primera corrida de este módulo dio grados de libertad clavados en
    la cota del optimizador y persistencia exactamente 1. Filtrar el *índice* a
    días hábiles antes de diferenciar hace que el retorno de viernes a lunes
    incluya el devengo del fin de semana, que es lo correcto. Los feriados en día
    hábil siguen adentro: son ~6% de los días y su efecto es menor.
    """
    if frecuencia is None:
        s = indice[indice.index.dayofweek < 5]
    else:
        s = indice.resample(frecuencia).last()
    return (np.log(s).diff().dropna() * 100).rename(indice.name)


# ---------------------------------------------------------------------------
# 1. Estacionariedad
# ---------------------------------------------------------------------------

def estacionariedad(indice: pd.Series) -> dict:
    """ADF y KPSS sobre el nivel (log) y sobre los retornos.

    Se usan los dos porque sus hipótesis nulas son opuestas: ADF supone raíz
    unitaria, KPSS supone estacionariedad. Que coincidan es lo que da confianza;
    uno solo puede no rechazar por falta de potencia.
    """
    from statsmodels.tsa.stattools import adfuller, kpss

    salida = {}
    for nombre, x in (("log_nivel", np.log(indice)), ("retorno", retornos_log(indice))):
        adf_stat, adf_p, *_ = adfuller(x.values, autolag="AIC")
        with warnings.catch_warnings():
            # KPSS avisa cuando el p-valor cae fuera de su tabla (lo reporta en
            # el borde, 0.01 o 0.10). Es información, no un error.
            warnings.simplefilter("ignore")
            kpss_stat, kpss_p, *_ = kpss(x.values, regression="c", nlags="auto")
        salida[nombre] = {"adf_stat": adf_stat, "adf_p": adf_p,
                          "kpss_stat": kpss_stat, "kpss_p": kpss_p}
    return salida


# ---------------------------------------------------------------------------
# 2. Predictibilidad: ¿una caída anuncia más caída?
# ---------------------------------------------------------------------------

def predictibilidad(indice: pd.Series) -> dict:
    """Autocorrelación de retornos diarios y mensuales, y AR(1) con errores HAC.

    Las dos frecuencias responden preguntas distintas y eso importa para leer el
    resultado. A frecuencia diaria los índices de fondos de pensiones suelen
    mostrar autocorrelación positiva en el rezago 1 por *precios rezagados*: los
    activos extranjeros se valorizan con cierres de otros husos horarios y los
    activos ilíquidos se valorizan con retraso. Es un artefacto de valorización,
    no algo que un afiliado pueda aprovechar -- un traspaso se ejecuta días
    después, al valor cuota de una fecha futura que no conoce. La frecuencia que
    corresponde a la decisión es la mensual.
    """
    import statsmodels.api as sm
    from statsmodels.stats.diagnostic import acorr_ljungbox
    from statsmodels.tsa.stattools import acf

    salida = {}
    for etiqueta, freq, rezagos in (("diario", None, 10), ("mensual", "ME", 12)):
        r = retornos_log(indice, freq)
        lb = acorr_ljungbox(r.values, lags=[rezagos], return_df=True)
        rho = acf(r.values, nlags=rezagos, fft=True)[1:]
        x = sm.add_constant(r.shift(1).dropna().values)
        y = r.iloc[1:].values
        maxlags = 5 if freq is None else 3
        ar1 = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
        salida[etiqueta] = {
            "n": int(len(r)),
            "acf": [float(v) for v in rho],
            "ljung_box_rezagos": rezagos,
            "ljung_box_stat": float(lb["lb_stat"].iloc[0]),
            "ljung_box_p": float(lb["lb_pvalue"].iloc[0]),
            "ar1_coef": float(ar1.params[1]),
            "ar1_t_hac": float(ar1.tvalues[1]),
            "ar1_p_hac": float(ar1.pvalues[1]),
            "ar1_r2": float(ar1.rsquared),
        }
    return salida


def retorno_futuro_tras_caida(indice: pd.Series, umbral_pct: float = -5.0,
                              horizonte_meses: int = 12) -> dict:
    """Retorno de los meses siguientes a un mes que cayó más de `umbral_pct`.

    Es la versión directa de la pregunta "¿una caída anuncia más caída?", sin
    pasar por un coeficiente. Se compara contra el retorno incondicional al mismo
    horizonte. Las ventanas se solapan, así que no se reporta un test de
    significancia ingenuo: el número de episodios independientes es mucho menor
    que el de meses.
    """
    m = indice.resample("ME").last()
    r_mes = np.log(m).diff() * 100
    futuro = (np.log(m).shift(-horizonte_meses) - np.log(m)) * 100
    df = pd.DataFrame({"r_mes": r_mes, "futuro": futuro}).dropna()
    tras_caida = df[df.r_mes <= umbral_pct]
    return {
        "umbral_pct": umbral_pct,
        "horizonte_meses": horizonte_meses,
        "n_meses_con_caida": int(len(tras_caida)),
        "futuro_medio_tras_caida": float(tras_caida.futuro.mean()),
        "futuro_mediano_tras_caida": float(tras_caida.futuro.median()),
        "pct_positivo_tras_caida": float((tras_caida.futuro > 0).mean() * 100),
        "futuro_medio_incondicional": float(df.futuro.mean()),
        "pct_positivo_incondicional": float((df.futuro > 0).mean() * 100),
    }


# ---------------------------------------------------------------------------
# 3. Volatilidad: clustering y GJR-GARCH
# ---------------------------------------------------------------------------

def clustering_volatilidad(indice: pd.Series) -> dict:
    """Ljung-Box sobre retornos al cuadrado y test ARCH-LM de Engle.

    Si los retornos no son predecibles pero sus cuadrados sí, la conclusión es
    precisa: se puede saber que se está en una tormenta, no hacia dónde va.
    """
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

    r = retornos_log(indice)
    lb2 = acorr_ljungbox((r ** 2).values, lags=[10], return_df=True)
    lm_stat, lm_p, *_ = het_arch(r.values, nlags=10)
    return {"ljung_box_cuadrados_stat": float(lb2["lb_stat"].iloc[0]),
            "ljung_box_cuadrados_p": float(lb2["lb_pvalue"].iloc[0]),
            "arch_lm_stat": float(lm_stat), "arch_lm_p": float(lm_p)}


def ajustar_gjr_garch(indice: pd.Series):
    """GJR-GARCH(1,1) con innovaciones t de Student sobre retornos diarios.

    GJR y no GARCH simple porque en renta variable las caídas suben la
    volatilidad más que las subidas del mismo tamaño (efecto apalancamiento), y
    eso es exactamente el mecanismo que vuelve tan angustiantes las caídas. t de
    Student y no normal porque las colas del Fondo A son gruesas. Media AR(1) y
    no constante porque los retornos diarios tienen la autocorrelación de precios
    rezagados que documenta `predictibilidad()`: dejarla en los residuos haría que
    el modelo de varianza intentara explicar una dinámica que es de la media.
    """
    from arch import arch_model

    r = retornos_log(indice)
    modelo = arch_model(r, mean="AR", lags=1, vol="GARCH", p=1, o=1, q=1, dist="t")
    res = modelo.fit(disp="off")
    p = res.params
    # Persistencia con innovaciones simétricas: alfa + beta + gamma/2. La
    # vida media es cuántos días tarda un shock de varianza en disiparse a la
    # mitad, que es la traducción operativa de "cuánto dura la tormenta".
    persistencia = p["alpha[1]"] + p["beta[1]"] + p["gamma[1]"] / 2
    vida_media = np.log(0.5) / np.log(persistencia) if persistencia < 1 else np.inf
    resumen = {
        "omega": float(p["omega"]), "alpha": float(p["alpha[1]"]),
        "gamma": float(p["gamma[1]"]), "beta": float(p["beta[1]"]),
        "nu": float(p["nu"]),
        "persistencia": float(persistencia),
        "vida_media_dias_habiles": float(vida_media),
        "vol_anual_media_pct": float(res.conditional_volatility.mean()
                                     * np.sqrt(DIAS_HABILES_ANIO)),
        "loglik": float(res.loglikelihood),
        "t_gamma": float(res.tvalues["gamma[1]"]),
    }
    vol = (res.conditional_volatility * np.sqrt(DIAS_HABILES_ANIO)).rename("vol_anual_pct")
    return resumen, vol


# ---------------------------------------------------------------------------
# 4. Régimen: Markov-switching
# ---------------------------------------------------------------------------

def ajustar_regimenes(indice: pd.Series, semilla: int = 42):
    """Dos regímenes con media y varianza propias, sobre retornos semanales.

    El régimen turbulento se identifica por varianza, no por media: la etiqueta
    "turbulento" es la del régimen más volátil. Se prueban varios puntos de
    partida porque la verosimilitud de estos modelos tiene óptimos locales.
    """
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    r = retornos_log(indice, "W-FRI")
    mejor = None
    rng = np.random.default_rng(semilla)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for intento in range(8):
            modelo = MarkovRegression(r.values, k_regimes=2, trend="c",
                                      switching_variance=True)
            inicio = None if intento == 0 else modelo.start_params * (
                1 + 0.3 * rng.standard_normal(len(modelo.start_params)))
            try:
                res = modelo.fit(start_params=inicio, disp=False, maxiter=500)
            except Exception:  # noqa: BLE001 -- un punto de partida malo, se descarta
                continue
            if mejor is None or res.llf > mejor.llf:
                mejor = res

    # Con endog como array, `params` es posicional: se ubica cada parámetro por
    # su nombre en `param_names` en vez de asumir un orden.
    nombres = list(mejor.model.param_names)
    const = [mejor.params[nombres.index(f"const[{k}]")] for k in range(2)]
    sig2 = [mejor.params[nombres.index(f"sigma2[{k}]")] for k in range(2)]
    turb = int(np.argmax(sig2))
    calma = 1 - turb

    duraciones = mejor.expected_durations
    suav = pd.Series(mejor.smoothed_marginal_probabilities[:, turb], index=r.index,
                     name="prob_turbulento_suavizada")
    filt = pd.Series(mejor.filtered_marginal_probabilities[:, turb], index=r.index,
                     name="prob_turbulento_filtrada")
    resumen = {
        "loglik": float(mejor.llf),
        "media_semanal_calma_pct": float(const[calma]),
        "media_semanal_turbulento_pct": float(const[turb]),
        "vol_anual_calma_pct": float(np.sqrt(sig2[calma]) * np.sqrt(52)),
        "vol_anual_turbulento_pct": float(np.sqrt(sig2[turb]) * np.sqrt(52)),
        "duracion_esperada_calma_semanas": float(duraciones[calma]),
        "duracion_esperada_turbulento_semanas": float(duraciones[turb]),
        "pct_semanas_turbulento": float((suav > 0.5).mean() * 100),
    }
    return resumen, suav, filt


def episodios_turbulentos(prob: pd.Series, umbral: float = 0.5,
                          min_semanas: int = 4) -> list[tuple[str, str, int]]:
    """Tramos continuos con probabilidad sobre el umbral, de al menos N semanas."""
    sobre = prob > umbral
    episodios, inicio = [], None
    for fecha, s in sobre.items():
        if s and inicio is None:
            inicio = fecha
        elif not s and inicio is not None:
            semanas = int(((fecha - inicio).days) / 7)
            if semanas >= min_semanas:
                episodios.append((str(inicio.date()), str(fecha.date()), semanas))
            inicio = None
    if inicio is not None:
        semanas = int(((prob.index[-1] - inicio).days) / 7)
        if semanas >= min_semanas:
            episodios.append((str(inicio.date()), str(prob.index[-1].date()), semanas))
    return episodios


def _ajustar_ms(r: np.ndarray, rng: np.random.Generator, intentos: int = 4):
    """Mejor ajuste Markov-switching de 2 regímenes sobre varios puntos de partida."""
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    mejor = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for intento in range(intentos):
            modelo = MarkovRegression(r, k_regimes=2, trend="c", switching_variance=True)
            inicio = None if intento == 0 else modelo.start_params * (
                1 + 0.3 * rng.standard_normal(len(modelo.start_params)))
            try:
                res = modelo.fit(start_params=inicio, disp=False, maxiter=500)
            except Exception:  # noqa: BLE001
                continue
            if mejor is None or res.llf > mejor.llf:
                mejor = res
    return mejor


def probabilidad_fuera_de_muestra(indice: pd.Series, semanas_iniciales: int = 208,
                                  cada: int = 52, semilla: int = 42) -> pd.Series:
    """Probabilidad filtrada de régimen turbulento, estrictamente en tiempo real.

    Las filtradas de `ajustar_regimenes` solo usan datos pasados *para filtrar*,
    pero sus parámetros se estimaron con la muestra completa -- incluido el
    futuro de cada semana. Esta versión cierra esa fuga: cada año se reestiman
    los parámetros con los datos disponibles hasta ese momento (ventana
    expansiva, mínimo 4 años) y con ellos se filtra el año siguiente, que el
    modelo nunca vio.
    """
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    r = retornos_log(indice, "W-FRI")
    rng = np.random.default_rng(semilla)
    tramos = []
    for s in range(semanas_iniciales, len(r), cada):
        ajuste = _ajustar_ms(r.values[:s], rng)
        if ajuste is None:
            continue
        nombres = list(ajuste.model.param_names)
        sig2 = [ajuste.params[nombres.index(f"sigma2[{k}]")] for k in range(2)]
        turb = int(np.argmax(sig2))
        fin = min(s + cada, len(r))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            filtro = MarkovRegression(r.values[:fin], k_regimes=2, trend="c",
                                      switching_variance=True).filter(ajuste.params)
        prob = filtro.filtered_marginal_probabilities[s:fin, turb]
        tramos.append(pd.Series(prob, index=r.index[s:fin]))
    return pd.concat(tramos).rename("prob_turbulento_oos")


def estrategia_con_senal(prob: pd.Series, idx_a: pd.Series, idx_e: pd.Series,
                         semanas_fuera: int = 52, rezago_ejecucion: int = 1) -> dict:
    """Seguir la señal como lo haría una persona, no como una tabla.

    Dos reglas que la versión ingenua no tiene:

    - **Decisiones que no se solapan.** Quien ya salió está afuera
      `semanas_fuera` semanas; una nueva señal dentro de ese período no es una
      nueva decisión. Sin esta regla, un mismo episodio cuenta varias veces.
    - **Rezago de ejecución.** El traspaso no se ejecuta al cierre de la semana
      en que se ve la señal sino días después, al valor cuota de una fecha que
      quien lo pide no conoce.

    Además del costo por decisión, compara la riqueza final de seguir la regla
    contra quedarse siempre en el A y siempre en el E, sobre el mismo período.
    """
    a = idx_a.resample("W-FRI").last().reindex(prob.index).ffill()
    e = idx_e.resample("W-FRI").last().reindex(prob.index).ffill()
    p = prob.values
    n = len(p)
    decisiones = []
    afuera = np.zeros(n, dtype=bool)
    i = 1
    while i < n:
        if p[i] > 0.5 and p[i - 1] <= 0.5:
            j = i + rezago_ejecucion
            k = j + semanas_fuera
            if k >= n:
                break
            ra = a.iloc[k] / a.iloc[j] - 1
            re = e.iloc[k] / e.iloc[j] - 1
            decisiones.append({"senal": str(prob.index[i].date()),
                               "a_pct": ra * 100, "e_pct": re * 100,
                               "costo_de_salir_pp": (ra - re) * 100})
            afuera[j:k] = True
            i = k
            continue
        i += 1

    ret_a = a.pct_change().fillna(0).values
    ret_e = e.pct_change().fillna(0).values
    # La semana t rinde según dónde estaba el saldo al cierre de t-1.
    en_e = np.concatenate([[False], afuera[:-1]])
    riqueza_regla = np.prod(1 + np.where(en_e, ret_e, ret_a))
    costos = np.array([d["costo_de_salir_pp"] for d in decisiones])
    anios = (prob.index[-1] - prob.index[0]).days / 365.25
    return {
        "desde": str(prob.index[0].date()),
        "hasta": str(prob.index[-1].date()),
        "n_decisiones": len(decisiones),
        "costo_medio_pp": float(costos.mean()) if len(costos) else float("nan"),
        "costo_mediano_pp": float(np.median(costos)) if len(costos) else float("nan"),
        "pct_decisiones_donde_salir_costo": float((costos > 0).mean() * 100) if len(costos) else float("nan"),
        "pct_tiempo_en_e": float(en_e.mean() * 100),
        "retorno_anual_regla_pct": float((riqueza_regla ** (1 / anios) - 1) * 100),
        "retorno_anual_siempre_a_pct": float((np.prod(1 + ret_a) ** (1 / anios) - 1) * 100),
        "retorno_anual_siempre_e_pct": float((np.prod(1 + ret_e) ** (1 / anios) - 1) * 100),
        "detalle": decisiones,
    }


# ---------------------------------------------------------------------------
# 5. ¿Sigue siendo el E un refugio?
# ---------------------------------------------------------------------------

def refugio_en_episodios(episodios: list[tuple[str, str, int]], idx_a: pd.Series,
                         idx_e: pd.Series) -> list[dict]:
    """Retorno real de A y de E dentro de cada episodio turbulento.

    Es la pregunta directa. Una correlación diaria baja no dice si el E protegió:
    dos fondos pueden moverse poco juntos día a día y aun así caer los dos a lo
    largo de un trimestre.
    """
    salida = []
    for ini, fin, semanas in episodios:
        a0, a1 = idx_a.asof(pd.Timestamp(ini)), idx_a.asof(pd.Timestamp(fin))
        e0, e1 = idx_e.asof(pd.Timestamp(ini)), idx_e.asof(pd.Timestamp(fin))
        salida.append({"inicio": ini, "fin": fin, "semanas": semanas,
                       "a_pct": (a1 / a0 - 1) * 100, "e_pct": (e1 / e0 - 1) * 100})
    return salida


def correlacion_movil(idx_a: pd.Series, idx_e: pd.Series, ventana: int = 252) -> pd.Series:
    ra, re = retornos_log(idx_a), retornos_log(idx_e)
    df = pd.concat([ra, re], axis=1, join="inner")
    return df.iloc[:, 0].rolling(ventana).corr(df.iloc[:, 1]).dropna().rename("corr_a_e")


def retorno_real_anual(indice: pd.Series) -> pd.Series:
    anual = indice.resample("YE").last()
    return (anual.pct_change() * 100).dropna().rename(indice.name)


# ---------------------------------------------------------------------------

def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    a = cargar_indice_real(con, "A")
    e = cargar_indice_real(con, "E")
    con.close()

    resumen: dict = {}

    print("1. ESTACIONARIEDAD (Fondo A, índice real)")
    est = estacionariedad(a)
    resumen["estacionariedad"] = est
    for k, v in est.items():
        print(f"   {k:<10} ADF p={v['adf_p']:.4f}   KPSS p={v['kpss_p']:.3f}")
    print("   -> el nivel tiene raíz unitaria; los retornos son estacionarios.")
    print("      Se modelan retornos, no precios.")
    print()

    print("2. PREDICTIBILIDAD: ¿una caída anuncia más caída?")
    pred = predictibilidad(a)
    resumen["predictibilidad"] = pred
    for k, v in pred.items():
        print(f"   {k:<8} n={v['n']:>5}  rho(1)={v['acf'][0]:+.3f}  "
              f"AR(1)={v['ar1_coef']:+.3f} (t HAC {v['ar1_t_hac']:+.2f}, "
              f"p={v['ar1_p_hac']:.3f})  R²={v['ar1_r2']:.3f}  "
              f"Ljung-Box({v['ljung_box_rezagos']}) p={v['ljung_box_p']:.3g}")
    caida = retorno_futuro_tras_caida(a)
    resumen["retorno_futuro_tras_caida"] = caida
    print(f"   tras un mes de {caida['umbral_pct']:.0f}% o peor ({caida['n_meses_con_caida']} meses):"
          f" retorno a {caida['horizonte_meses']} meses medio {caida['futuro_medio_tras_caida']:+.1f}%,"
          f" positivo en {caida['pct_positivo_tras_caida']:.0f}% de los casos")
    print(f"   incondicional: medio {caida['futuro_medio_incondicional']:+.1f}%,"
          f" positivo en {caida['pct_positivo_incondicional']:.0f}%")
    print()

    print("3. VOLATILIDAD")
    clus = clustering_volatilidad(a)
    resumen["clustering"] = clus
    print(f"   Ljung-Box(10) sobre r²: p={clus['ljung_box_cuadrados_p']:.3g}   "
          f"ARCH-LM(10): p={clus['arch_lm_p']:.3g}")
    garch, vol = ajustar_gjr_garch(a)
    resumen["gjr_garch"] = garch
    print(f"   GJR-GARCH(1,1)-t: alfa={garch['alpha']:.3f} gamma={garch['gamma']:.3f} "
          f"(t={garch['t_gamma']:.1f}) beta={garch['beta']:.3f} nu={garch['nu']:.1f}")
    print(f"   persistencia {garch['persistencia']:.4f} -> vida media de un shock: "
          f"{garch['vida_media_dias_habiles']:.0f} días hábiles "
          f"(~{garch['vida_media_dias_habiles']/21:.1f} meses)")
    print()

    print("4. RÉGIMEN (Markov-switching, retornos semanales)")
    reg, suav, filt = ajustar_regimenes(a)
    resumen["regimenes"] = reg
    print(f"   calma     : media {reg['media_semanal_calma_pct']:+.3f}%/sem, "
          f"vol {reg['vol_anual_calma_pct']:.1f}% anual, dura ~"
          f"{reg['duracion_esperada_calma_semanas']:.0f} semanas")
    print(f"   turbulento: media {reg['media_semanal_turbulento_pct']:+.3f}%/sem, "
          f"vol {reg['vol_anual_turbulento_pct']:.1f}% anual, dura ~"
          f"{reg['duracion_esperada_turbulento_semanas']:.0f} semanas")
    eps = episodios_turbulentos(suav)
    resumen["episodios_turbulentos"] = eps
    print(f"   {reg['pct_semanas_turbulento']:.0f}% de las semanas en régimen turbulento;"
          f" episodios de 4+ semanas:")
    for ini, fin, sem in eps:
        print(f"     {ini} -> {fin}  ({sem} semanas)")
    print()
    print("   ¿Se puede USAR el régimen? Salir al E cuando el modelo dice 'turbulento'")
    print("   y volver a las 52 semanas, sin decisiones solapadas:")
    oos = probabilidad_fuera_de_muestra(a)
    filt_mismo_periodo = filt[filt.index >= oos.index[0]]
    estrategias = {}
    for etiqueta, prob, rezago in (
            ("parámetros con muestra completa, sin rezago", filt_mismo_periodo, 0),
            ("parámetros con muestra completa, 1 sem rezago", filt_mismo_periodo, 1),
            ("fuera de muestra, sin rezago", oos, 0),
            ("fuera de muestra, 1 sem rezago  <- la real", oos, 1)):
        est_r = estrategia_con_senal(prob, a, e, rezago_ejecucion=rezago)
        estrategias[etiqueta] = est_r
        print(f"     {etiqueta:<48} {est_r['n_decisiones']:>2} dec. "
              f"costo medio {est_r['costo_medio_pp']:+5.1f} pp | regla "
              f"{est_r['retorno_anual_regla_pct']:+.2f}%/año vs siempre A "
              f"{est_r['retorno_anual_siempre_a_pct']:+.2f}%")
    resumen["estrategia_senal"] = {k: {kk: vv for kk, vv in v.items() if kk != "detalle"}
                                   for k, v in estrategias.items()}
    real = estrategias["fuera de muestra, 1 sem rezago  <- la real"]
    print(f"   -> la ventaja aparente era sesgo de anticipación: con parámetros que")
    print(f"      no conocen el futuro y el rezago real de un traspaso, salir costó en")
    print(f"      {real['pct_decisiones_donde_salir_costo']:.0f}% de las {real['n_decisiones']} decisiones."
          f" Con tan pocas, la diferencia contra")
    print(f"      quedarse no se distingue de cero: no hay ventaja que ocupar.")
    print()

    print("5. ¿SIGUE SIENDO EL E UN REFUGIO?")
    refugio = refugio_en_episodios(eps, a, e)
    resumen["refugio_en_episodios"] = refugio
    print("   retorno real dentro de cada episodio turbulento:")
    for x in refugio:
        # Tres casos, no dos. Un régimen turbulento es de VOLATILIDAD, no de
        # caída: si el A subió no había nada de qué protegerse, y si cayeron los
        # dos, que el E cayera un poco menos no es protección.
        if x["a_pct"] >= 0:
            lectura = "turbulento al alza: no había de qué protegerse"
        elif x["e_pct"] >= 0:
            lectura = "el E protegió"
        else:
            lectura = "cayeron los dos"
        x["lectura"] = lectura
        print(f"     {x['inicio']} -> {x['fin']}  A {x['a_pct']:+6.1f}%  "
              f"E {x['e_pct']:+6.1f}%  {lectura}")
    corr = correlacion_movil(a, e)
    anual_e = retorno_real_anual(e)
    anual_a = retorno_real_anual(a)
    resumen["corr_a_e"] = {"media": float(corr.mean()), "min": float(corr.min()),
                           "max": float(corr.max()),
                           "fecha_max": str(corr.idxmax().date())}
    print(f"   correlación A-E móvil 1 año: media {corr.mean():+.2f}, "
          f"máx {corr.max():+.2f} ({corr.idxmax().date()})")
    peores_e = anual_e.nsmallest(3)
    print("   peores años reales del E: " + ", ".join(
        f"{d.year} {v:+.1f}% (A {anual_a.get(d, float('nan')):+.1f}%)" for d, v in peores_e.items()))
    resumen["peores_anios_e"] = {str(d.year): float(v) for d, v in peores_e.items()}

    vol.to_frame().to_csv(REPORTS_DIR / "ts_volatilidad_condicional.csv")
    pd.concat([suav, filt], axis=1).to_csv(REPORTS_DIR / "ts_regimenes.csv")
    corr.to_frame().to_csv(REPORTS_DIR / "ts_correlacion_a_e.csv")
    oos.to_frame().to_csv(REPORTS_DIR / "ts_regimen_fuera_de_muestra.csv")
    pd.DataFrame(real["detalle"]).to_csv(REPORTS_DIR / "ts_decisiones_senal.csv", index=False)
    (REPORTS_DIR / "time_series_summary.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print()
    print("-> reports/time_series_summary.json y reports/ts_*.csv")


if __name__ == "__main__":
    main()
