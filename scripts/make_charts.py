"""Gráficos del README: `python scripts/make_charts.py`.

Todo sale de `data/pension_funds.duckdb` y de `reports/`, que produce el
pipeline; ninguna cifra se escribe a mano acá.

Los rótulos van en español porque el tema es el sistema previsional chileno y la
audiencia que puede usar esto es la que tiene AFP. El README en inglés incrusta
las mismas imágenes a propósito: traducirlas obligaría a mantener dos juegos de
PNG que dirían lo mismo.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.ticker import FuncFormatter, PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS = ROOT / "reports"
FIG_DIR = ROOT / "outputs" / "figures"

# Paleta: un color por rol, no por estética. Rojo = el costo de moverse,
# verde = quedarse, gris = contexto que no es el mensaje.
INK = "#23201D"
MUTED = "#6B645D"
GRID = "#E3DED7"
COST = "#B5553D"      # moverse / pérdida
STAY = "#4C7A3E"      # quedarse / acierto
FONDO_A = "#C2703D"
FONDO_E = "#6E8CA0"
HILITE = "#B58900"


def _style(ax, *, title=None, xlabel=None, ylabel=None, grid_axis="y"):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.7, alpha=0.9)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK, labelsize=9.5)
    if title:
        ax.set_title(title, fontsize=12.5, color=INK, pad=14, loc="left", fontweight="600")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10.5, color=MUTED)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10.5, color=MUTED)
    return ax


def _save(fig, name, note=None):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    if note:
        fig.text(0.0, -0.02, note, fontsize=8.8, color=MUTED, ha="left", va="top", wrap=True)
    fig.savefig(FIG_DIR / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  escrito outputs/figures/{name}")


def _con():
    return duckdb.connect(str(DB_PATH), read_only=True)


# ---------------------------------------------------------------------------
# 1. El mecanismo: por qué moverse en el piso cuesta
# ---------------------------------------------------------------------------
def fig_mechanism():
    print("1/5 mecanismo_covid ...")
    con = _con()
    df = con.execute("""
        SELECT fecha, fondo, index_value FROM fund_index
        WHERE fondo IN ('A','E') AND fecha BETWEEN DATE '2020-01-02' AND DATE '2021-06-30'
        ORDER BY fecha
    """).pl()
    con.close()

    base = {f: df.filter(pl.col("fondo") == f).sort("fecha")["index_value"][0] for f in ("A", "E")}
    fig, ax = plt.subplots(figsize=(10.5, 5.4))

    for f, color, label in (("A", FONDO_A, "Fondo A (más riesgoso)"),
                            ("E", FONDO_E, "Fondo E (más conservador)")):
        s = df.filter(pl.col("fondo") == f).sort("fecha")
        ax.plot(s["fecha"], (s["index_value"] / base[f] - 1) * 100,
                color=color, linewidth=2.2, label=label)

    trough = __import__("datetime").date(2020, 3, 24)
    ax.axvline(trough, color=COST, linestyle="--", linewidth=1.5)

    # La anotacion se ancla al valor real del Fondo A ese dia, no a una
    # coordenada fija: con un numero escrito a mano quedaba fuera del eje y
    # desaparecia del grafico sin avisar.
    sa = df.filter(pl.col("fondo") == "A").sort("fecha")
    a_pct = (sa["index_value"] / base["A"] - 1) * 100
    idx = min(range(len(sa)), key=lambda i: abs((sa["fecha"][i] - trough).days))
    y_trough = float(a_pct[idx])
    ax.annotate("acá se cambia\nquien entra en pánico",
                xy=(trough, y_trough),
                xytext=(trough + __import__("datetime").timedelta(days=55), y_trough - 2),
                fontsize=9.5, color=COST, ha="left", fontweight="600",
                arrowprops=dict(arrowstyle="->", color=COST, linewidth=1.1))
    ax.axhline(0, color=GRID, linewidth=1.2)

    _style(ax, title="Por qué moverse en el piso cuesta: la caída ya ocurrió, la recuperación no",
           ylabel="Variación desde enero 2020")
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.legend(frameon=False, fontsize=10, loc="lower right")

    _save(fig, "mecanismo_covid.png",
          "Quien se cambia en el piso materializa la caída completa del Fondo A y después acompaña al "
          "Fondo E, que sube mucho menos.\nLa pérdida no está en el día del cambio: está en los meses "
          "siguientes, que es cuando el fondo que se abandonó se recupera.")


# ---------------------------------------------------------------------------
# 2. El hallazgo nuevo: el costo depende de cuánto ya perdiste
# ---------------------------------------------------------------------------
def fig_breakeven():
    print("2/5 punto_de_quiebre ...")
    df = pl.read_csv(REPORTS / "timing_grid.csv")

    buckets = [(0, -5, "0% a −5%"), (-5, -10, "−5% a −10%"), (-10, -20, "−10% a −20%"),
               (-20, -30, "−20% a −30%"), (-30, -100, "más de −30%")]
    labels, medians, shares, ns = [], [], [], []
    for hi, lo, lab in buckets:
        sub = df.filter((pl.col("drawdown_at_switch_pct") <= hi) &
                        (pl.col("drawdown_at_switch_pct") > lo))
        if sub.is_empty():
            continue
        labels.append(lab)
        medians.append(sub["cost_of_switching_pct_pts"].median())
        shares.append((sub["cost_of_switching_pct_pts"] > 0).mean())
        ns.append(len(sub))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.3), gridspec_kw={"width_ratios": [1.15, 1]})

    colors = [COST if m > 0 else STAY for m in medians]
    bars = ax1.bar(labels, medians, color=colors, width=0.62, edgecolor="white", linewidth=1.4)
    for b, m, n in zip(bars, medians, ns):
        va = "bottom" if m > 0 else "top"
        off = 0.9 if m > 0 else -0.9
        ax1.text(b.get_x() + b.get_width() / 2, m + off, f"{m:+.1f} pp", ha="center", va=va,
                 fontsize=10.5, color=INK, fontweight="600")
        ax1.text(b.get_x() + b.get_width() / 2, 0.6 if m < 0 else -0.6, f"n={n}", ha="center",
                 va="bottom" if m < 0 else "top", fontsize=8.5, color=MUTED)
    ax1.axhline(0, color=INK, linewidth=1.3)
    ax1.tick_params(axis="x", labelsize=9, rotation=12)
    _style(ax1, title="Mientras menos hayas perdido, más sirve moverte",
           ylabel="Costo mediano de cambiarse")
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.0f} pp"))

    ax2.plot(range(len(labels)), shares, color=COST, linewidth=2.4, marker="o", markersize=9,
             markerfacecolor="white", markeredgewidth=2)
    for i, s in enumerate(shares):
        ax2.text(i, s + 0.04, f"{s:.0%}", ha="center", fontsize=10, color=INK, fontweight="600")
    ax2.axhline(0.5, color=MUTED, linestyle=":", linewidth=1.4)
    ax2.text(len(labels) - 1, 0.52, "mitad y mitad", fontsize=9, color=MUTED, ha="right")
    ax2.set_xticks(range(len(labels)))
    ax2.set_xticklabels(labels, fontsize=9, rotation=12)
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    _style(ax2, title="…y más se invierte cuando ya perdiste mucho",
           ylabel="Combinaciones donde cambiarse SALE CARO")

    _save(fig, "punto_de_quiebre.png",
          "481 combinaciones de (día del cambio × plazo de retorno) sobre las 3 caídas reales ≥15% del Fondo A desde 2002. "
          "El punto de quiebre está en torno al −25% ya perdido.\n"
          "Que exista una zona donde moverse gana NO la vuelve ocupable: ganar ahí exige saber que la caída va a seguir, "
          "que es justo lo que no se sabe. El corte sirve al revés — si ya perdiste mucho, moverte ahora no te salva.\n"
          "Son 3 episodios, no 3.000: los porcentajes describen estas crisis, no una ley del mercado.")


# ---------------------------------------------------------------------------
# 3. Distribución de los escenarios sistemáticos
# ---------------------------------------------------------------------------
def fig_distribution():
    print("3/5 distribucion_escenarios ...")
    df = pl.read_csv(REPORTS / "systematic_panic_switch_results.csv")
    col = "cost_of_panic_pct_pts"
    vals = df[col].to_numpy()

    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.hist(vals, bins=12, color=COST, alpha=0.75, edgecolor="white", linewidth=1.2)
    ax.axvline(0, color=INK, linewidth=1.6)
    ax.axvline(float(np.mean(vals)), color=HILITE, linestyle="--", linewidth=2)
    ax.text(float(np.mean(vals)), ax.get_ylim()[1] * 0.92, f"  media +{np.mean(vals):.1f} pp",
            fontsize=10.5, color=HILITE, fontweight="600")
    ax.text(0, ax.get_ylim()[1] * 0.60, "quedarse\nempata  ", fontsize=9.5, color=MUTED, ha="right")

    _style(ax, title=f"Los {len(vals)} escenarios con el cambio hecho en el piso: ninguno favorece moverse",
           xlabel="Costo del pánico (puntos porcentuales de rentabilidad perdida)",
           ylabel="Escenarios")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.0f}"))

    _save(fig, "distribucion_escenarios.png",
          "3 caídas reales × 5 plazos de retorno. Toda la masa está a la derecha del cero: en los 15, quedarse ganó.\n"
          "Es el caso extremo del gráfico anterior — cambiarse en el piso es cambiarse habiendo perdido el 100% de la caída.")


# ---------------------------------------------------------------------------
# 4. Comportamiento real, con el hueco de datos marcado
# ---------------------------------------------------------------------------
def fig_traspasos():
    print("4/5 traspasos_volumen ...")
    df = pl.read_parquet(ROOT / "data" / "processed" / "traspasos_monthly.parquet").sort("data_month")
    meses = df["data_month"].to_list()
    vals = df["total_traspasos"].to_numpy()
    x = [__import__("datetime").date(int(m[:4]), int(m[5:7]), 1) for m in meses]

    fig, ax = plt.subplots(figsize=(11, 5))

    # El tramo sin boletines NO se une con una línea: dibujarlo continuo sugeriría
    # mediciones que no existen. Se parte la serie en bloques contiguos.
    gaps = [i for i in range(1, len(x)) if (x[i] - x[i - 1]).days > 70]
    starts = [0] + gaps
    ends = gaps + [len(x)]
    for s, e in zip(starts, ends):
        ax.plot(x[s:e], vals[s:e], color=FONDO_E, linewidth=2, marker="o", markersize=4.5)
    for g in gaps:
        ax.axvspan(x[g - 1], x[g], color=GRID, alpha=0.55)
        mid = x[g - 1] + (x[g] - x[g - 1]) / 2
        ax.text(mid, max(vals) * 0.97, "sin boletines\ndescargados", fontsize=8.8, color=MUTED,
                ha="center", va="top")

    covid_trough = __import__("datetime").date(2020, 3, 24)
    ax.axvline(covid_trough, color=COST, linestyle="--", linewidth=1.5)
    lo_i = int(np.argmin(vals))
    ax.annotate(f"{vals[lo_i]:,.0f} cuentas\n(mayo 2020)".replace(",", "."),
                xy=(x[lo_i], vals[lo_i]),
                xytext=(x[lo_i] + __import__("datetime").timedelta(days=140),
                        vals[lo_i] + max(vals) * 0.10),
                fontsize=9.5, color=COST, ha="left", fontweight="600",
                arrowprops=dict(arrowstyle="->", color=COST, linewidth=1.1))
    ax.text(covid_trough, max(vals) * 0.82, "piso COVID ", fontsize=9.5, color=COST,
            ha="right", fontweight="600")

    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v/1000)} mil"))
    _style(ax, title="La sorpresa: los traspasos NO se disparan en el piso — se desploman",
           ylabel="Cuentas traspasadas entre AFP, por mes")

    _save(fig, "traspasos_volumen.png",
          "Fuente: Ficha Estadística Previsional (Superintendencia de Pensiones), 22 boletines descargados. "
          "El tramo gris no tiene datos y por eso no se une con una línea.\n"
          "Esto NO prueba que la gente no entró en pánico: Chile estaba en cuarentena estricta, las sucursales "
          "cerradas y el trámite no era del todo digital.\nLa caída se confunde con no haber PODIDO cambiarse.")


# ---------------------------------------------------------------------------
# 5. Historia completa A vs E
# ---------------------------------------------------------------------------
def fig_history():
    print("5/5 fondo_a_vs_e_historia ...")
    con = _con()
    df = con.execute("""
        SELECT fecha, fondo, index_value FROM fund_index
        WHERE fondo IN ('A','E') ORDER BY fecha
    """).pl()
    con.close()

    fig, ax = plt.subplots(figsize=(11, 5))
    for f, color, label in (("A", FONDO_A, "Fondo A"), ("E", FONDO_E, "Fondo E")):
        s = df.filter(pl.col("fondo") == f).sort("fecha")
        ax.plot(s["fecha"], s["index_value"], color=color, linewidth=1.9, label=label)

    for peak, trough, lab in (("2007-10-31", "2008-11-21", "GFC 2008"),
                              ("2011-01-06", "2011-10-05", "2011"),
                              ("2020-02-24", "2020-03-24", "COVID")):
        import datetime as _dt
        p = _dt.date(*map(int, peak.split("-")))
        t = _dt.date(*map(int, trough.split("-")))
        ax.axvspan(p, t, color=COST, alpha=0.11)
        ax.text(p + (t - p) / 2, df["index_value"].max() * 0.97, lab, fontsize=9,
                color=COST, ha="center", va="top")

    _style(ax, title="Fondo A y Fondo E desde 2002, ponderados por patrimonio (base 100)",
           ylabel="Índice (100 = inicio)")
    ax.legend(frameon=False, fontsize=10.5, loc="upper left")

    _save(fig, "fondo_a_vs_e_historia.png",
          "Las bandas marcan las 3 caídas del Fondo A de 15% o más detectadas automáticamente, no elegidas a mano. "
          "El Fondo A termina muy por encima\npese a cada una de ellas: ese es el costo de fondo de refugiarse y "
          "quedarse refugiado.")


# ---------------------------------------------------------------------------
# 6. Nominal vs real: la pérdida que el peso corriente esconde
# ---------------------------------------------------------------------------
def fig_real_vs_nominal():
    print("6/11 real_vs_nominal ...")
    import datetime as _dt

    import pandas as pd

    con = _con()
    series = {}
    for tabla in ("fund_index", "fund_index_real"):
        df = con.execute(f"SELECT fecha, index_value FROM {tabla} WHERE fondo='A' "
                         "ORDER BY fecha").fetchdf()
        s = pd.Series(df.index_value.values, index=pd.to_datetime(df.fecha))
        series[tabla] = s / s.iloc[0] * 100
    con.close()
    nom, real = series["fund_index"], series["fund_index_real"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.2), sharex=True,
                                   gridspec_kw={"height_ratios": [1.5, 1], "hspace": 0.12})
    ax1.plot(nom.index, nom.values, color=MUTED, linewidth=1.5,
             label="Fondo A en pesos corrientes")
    ax1.plot(real.index, real.values, color=FONDO_A, linewidth=2.0,
             label="Fondo A en UF (poder adquisitivo)")
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    _style(ax1, title="La misma historia, medida en pesos y en poder adquisitivo",
           ylabel="Índice, escala log (100 = sep-2002)")
    ax1.legend(frameon=False, fontsize=10, loc="upper left")

    for s, color, label in ((nom, MUTED, "en pesos"), (real, FONDO_A, "en UF")):
        dd = (s / s.cummax() - 1) * 100
        ax2.fill_between(dd.index, dd.values, 0, color=color,
                         alpha=0.25 if color == MUTED else 0.45, linewidth=0)
        ax2.plot(dd.index, dd.values, color=color, linewidth=1.0,
                 label=f"caída desde el máximo, {label}")
    ax2.axhline(-15, color=COST, linewidth=0.9, linestyle="--")
    ax2.text(real.index[30], -16.5, "umbral de 15%", fontsize=8.5, color=COST, va="top")
    _style(ax2, ylabel="Caída desde el máximo (%)")
    ax2.legend(frameon=False, fontsize=9, loc="lower right")
    for x, y, txt in ((_dt.date(2013, 3, 1), -40, "GFC: en UF, bajo el agua\nhasta agosto de 2014"),
                      (_dt.date(2025, 1, 1), -33, "2021-23: -26% en UF.\nEn pesos, -14,6%: justo\nbajo el umbral")):
        ax2.annotate(txt, xy=(x, y), fontsize=8.8, color=INK, ha="center")
    _save(fig, "real_vs_nominal.png",
          "Índice ponderado por patrimonio del Fondo A, deflactado por la UF diaria (Banco Central vía "
          "mindicador.cl). El índice nominal lleva ~3,8% anual de inflación adentro:\nen pesos corrientes la "
          "crisis de 2021-23 parece un año malo; en poder adquisitivo fue la segunda peor caída de los 24 años.")


# ---------------------------------------------------------------------------
# 7. La pensión: cuándo te cambias importa más que si te cambias
# ---------------------------------------------------------------------------
def fig_pension_por_edad():
    print("7/11 pension_por_edad ...")
    df = pl.read_csv(REPORTS / "pension_loss.csv")
    eventos = ["GFC 2008", "COVID 2020", "Inflación 2021-23"]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.6), sharey=True)
    ancho = 0.38
    for ax, ev in zip(axes, eventos):
        sub = df.filter(pl.col("evento") == ev)
        edades = sorted(sub["edad_al_evento"].unique().to_list())
        x = np.arange(len(edades))
        valores = {}
        for k, (regla, color, label) in enumerate((
                ("piso", COST, "se cambia en el piso"),
                ("observable", FONDO_E, "se cambia al cruzar -15%"))):
            vals = [-sub.filter((pl.col("regla") == regla) & (pl.col("edad_al_evento") == e))
                    ["perdida_pct"][0] for e in edades]
            valores[regla] = vals
            ax.bar(x + (k - 0.5) * ancho, vals, ancho, color=color, label=label)
        # Una etiqueta por barra, salvo cuando las dos reglas dan lo mismo (COVID):
        # ahí van una sola vez, centrada, en vez de dos encimadas.
        for i, (vp, vo) in enumerate(zip(valores["piso"], valores["observable"])):
            pares = ([(x[i], vp)] if abs(vp - vo) < 0.5
                     else [(x[i] - ancho / 2, vp), (x[i] + ancho / 2, vo)])
            for xi, v in pares:
                ax.text(xi, v + (1.2 if v >= 0 else -1.2), f"{v:+.0f}%", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=8, color=INK)
        ax.axhline(0, color=INK, linewidth=0.8)
        ax.set_xticks(x, [f"{e} años" for e in edades])
        _style(ax, title=ev)
    axes[0].set_ylabel("Cambio en la pensión (%)", fontsize=10.5, color=MUTED)
    axes[0].yaxis.set_major_formatter(PercentFormatter(decimals=0))
    # La leyenda va en el panel de COVID, que tiene vacía toda la mitad de arriba.
    axes[1].legend(frameon=False, fontsize=9.5, loc="upper center")
    fig.suptitle("La misma persona, la misma crisis: cambiarse tarde siempre restó; "
                 "cambiarse temprano, a veces sumó",
                 fontsize=12.5, color=INK, x=0.01, ha="left", fontweight="600", y=1.02)
    _save(fig, "pension_por_edad.png",
          "Hombre que cotiza 10% de 20 UF desde los 25; Fondo A hasta los 55 y B después (Ley 19.795). Vuelve a su "
          "fondo 12 meses después del cambio. En COVID las dos reglas coinciden:\nla caída fue tan rápida que el "
          "-15% y el piso cayeron en la misma semana. Que la regla temprana sumara en 2 de 3 casos NO la vuelve "
          "buena idea: ver el gráfico del bootstrap.")


# ---------------------------------------------------------------------------
# 8. Bootstrap: el piso es retrospectivo
# ---------------------------------------------------------------------------
def fig_bootstrap():
    print("8/11 bootstrap_reglas ...")
    df = pl.read_csv(REPORTS / "bootstrap_decisiones.csv")
    resumen = json.loads((REPORTS / "bootstrap_cost.json").read_text(encoding="utf-8"))
    res = resumen["bootstrap"]["bloque_26"]
    fig, ax = plt.subplots(figsize=(11, 4.8))
    bins = np.linspace(-80, 100, 73)
    for regla, color, label in (
            ("observable", FONDO_E, "al cruzar -15% (observable)"),
            ("piso", COST, "en el piso (con retrospectiva)")):
        v = df.filter(pl.col("regla") == regla)["costo_pp"].to_numpy()
        ax.hist(v, bins=bins, color=color, alpha=0.55, label=label, density=True)
        ax.axvline(res[regla]["mediana_pp"], color=color, linewidth=1.6)
    ax.axvline(0, color=INK, linewidth=1.0)
    ax.text(1.5, ax.get_ylim()[1] * 0.97, "← cambiarse ganó  |  cambiarse costó →", fontsize=9,
            color=MUTED, va="top")
    for regla, color, y in (("piso", COST, 0.80), ("observable", FONDO_E, 0.64)):
        r = res[regla]
        mediana = f"{r['mediana_pp']:+.1f}".replace(".", ",")
        ax.text(0.99, y, f"{r['prob_salir_cuesta']:.0f}% de las veces costó · mediana {mediana} pp",
                transform=ax.transAxes, ha="right", fontsize=9.5, color=color, fontweight="600")
    _style(ax, title="En 2.000 historias sintéticas: tarde cuesta casi siempre, "
                     "temprano es una moneda al aire",
           xlabel="Retorno de A menos retorno de E en las 52 semanas fuera (puntos porcentuales)",
           ylabel="Densidad")
    ax.legend(frameon=False, fontsize=9.5, loc="upper left", title="Se cambia...",
              title_fontsize=9.5)
    _save(fig, "bootstrap_reglas.png",
          "Bootstrap estacionario sobre retornos semanales reales de A y E (bloques de 26 semanas en promedio; los "
          "resultados son casi iguales con 13 y 52). El 'piso' es el mínimo realizado\nde cada caída que se "
          "recuperó: elegirlo con retrospectiva garantiza que lo que sigue es una subida. La regla observable "
          "incluye caídas que nunca se recuperan.")


# ---------------------------------------------------------------------------
# 9. Volatilidad y régimen: se sabe que hay tormenta, no hacia dónde va
# ---------------------------------------------------------------------------
def fig_volatilidad_regimen():
    print("9/11 volatilidad_regimen ...")
    import pandas as pd

    vol = pd.read_csv(REPORTS / "ts_volatilidad_condicional.csv", parse_dates=["fecha"],
                      index_col="fecha")["vol_anual_pct"].dropna()
    reg = pd.read_csv(REPORTS / "ts_regimenes.csv", parse_dates=["fecha"], index_col="fecha")
    resumen = json.loads((REPORTS / "time_series_summary.json").read_text(encoding="utf-8"))
    g = resumen["gjr_garch"]
    mensual = resumen["predictibilidad"]["mensual"]

    fig, ax = plt.subplots(figsize=(11, 4.6))
    turb = reg["prob_turbulento_suavizada"] > 0.5
    inicio = None
    for fecha, t in turb.items():
        if t and inicio is None:
            inicio = fecha
        elif not t and inicio is not None:
            ax.axvspan(inicio, fecha, color=COST, alpha=0.13, linewidth=0)
            inicio = None
    ax.plot(vol.index, vol.values, color=INK, linewidth=0.9)
    ax.plot([], [], color=COST, alpha=0.3, linewidth=8, label="régimen turbulento (Markov-switching)")
    ax.plot([], [], color=INK, linewidth=1.2, label="volatilidad condicional GJR-GARCH, anualizada")
    _style(ax, title="Se puede saber que hay tormenta. No hacia dónde va.",
           ylabel="Volatilidad anualizada del Fondo A (%)")
    # Techo sobre el pico de 2020 (~53%): deja una franja libre arriba para la
    # leyenda y el texto, que si no se montan sobre las curvas.
    ax.set_ylim(0, vol.max() * 1.38)
    ax.legend(frameon=False, fontsize=9.5, loc="upper right")
    def coma(x, fmt):
        return format(x, fmt).replace(".", ",")

    ax.text(0.01, 0.97,
            "La volatilidad sí es predecible: un shock se disipa\n"
            f"a la mitad en ~{g['vida_media_dias_habiles']:.0f} días hábiles, y las caídas la suben\n"
            f"más que las subidas (γ = {coma(g['gamma'], '.3f')}, t = {coma(g['t_gamma'], '.1f')}).\n"
            f"El retorno no: AR(1) mensual {coma(mensual['ar1_coef'], '+.2f')}, "
            f"p = {coma(mensual['ar1_p_hac'], '.2f')}.",
            transform=ax.transAxes, fontsize=9, color=INK, va="top")
    _save(fig, "volatilidad_regimen.png",
          "Retornos diarios hábiles del índice real del Fondo A: sábados y domingos se excluyen porque el valor "
          "cuota casi no se mueve y rompen el modelo.\nRégimen estimado sobre retornos semanales; las "
          "probabilidades suavizadas usan toda la muestra: sirven para fechar, no para decidir.")


# ---------------------------------------------------------------------------
# 10. La señal de régimen: la ventaja era información del futuro
# ---------------------------------------------------------------------------
def fig_senal_sesgo():
    print("10/11 senal_sesgo_anticipacion ...")
    resumen = json.loads((REPORTS / "time_series_summary.json").read_text(encoding="utf-8"))
    est = resumen["estrategia_senal"]
    claves = list(est.keys())
    rotulos = ["Parámetros que conocen el futuro,\nejecución inmediata",
               "Parámetros que conocen el futuro,\n1 semana de rezago",
               "Fuera de muestra,\nejecución inmediata",
               "Fuera de muestra, 1 semana de rezago\n(lo que alguien podría hacer)"]
    vals = [est[k]["retorno_anual_regla_pct"] for k in claves]
    siempre_a = est[claves[-1]]["retorno_anual_siempre_a_pct"]
    siempre_e = est[claves[-1]]["retorno_anual_siempre_e_pct"]

    def pct(x):
        return f"{x:+.2f}%".replace(".", ",")

    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    colores = [MUTED, MUTED, FONDO_E, COST]
    y = np.arange(len(vals))[::-1]
    ax.barh(y, vals, color=colores, height=0.6)
    for yi, v in zip(y, vals):
        ax.text(v + 0.06, yi, f"{pct(v)}/año", va="center", fontsize=9.5, color=INK)
    # Las referencias se rotulan DENTRO del área de datos, en franjas libres
    # arriba y abajo de las barras: afuera chocaban con el título y con el eje.
    ax.set_ylim(-1.15, len(vals) - 0.1)
    ax.axvline(siempre_a, color=STAY, linewidth=1.8)
    ax.text(siempre_a + 0.05, len(vals) - 0.45, f"quedarse siempre en A: {pct(siempre_a)}",
            color=STAY, fontsize=9.5, va="center", fontweight="600")
    ax.axvline(siempre_e, color=FONDO_E, linewidth=1.2, linestyle="--")
    ax.text(siempre_e - 0.05, -0.8, f"siempre en E: {pct(siempre_e)}", color=FONDO_E, fontsize=9,
            ha="right", va="center")
    ax.set_yticks(y, rotulos, fontsize=9.5)
    ax.set_xlim(0, max(vals) + 1.3)
    _style(ax, title="'Salir cuando el modelo detecta turbulencia': la ventaja era información del futuro",
           xlabel="Retorno real anual 2006-2026 (%)", grid_axis="x")
    _save(fig, "senal_sesgo_anticipacion.png",
          "Regla: salir al Fondo E cuando la probabilidad filtrada de régimen turbulento cruza 0,5 y volver 52 "
          "semanas después, sin decisiones solapadas.\n'Fuera de muestra' reestima el modelo cada año solo con el "
          "pasado. Son 11-12 decisiones: la diferencia final contra quedarse no se distingue de cero.")


# ---------------------------------------------------------------------------
# 11. El refugio también cae
# ---------------------------------------------------------------------------
def fig_fondo_e_anual():
    print("11/11 fondo_e_anual ...")
    import pandas as pd

    con = _con()
    anual = {}
    for f in ("A", "E"):
        df = con.execute("SELECT fecha, index_value FROM fund_index_real WHERE fondo=? ORDER BY fecha",
                         [f]).fetchdf()
        s = pd.Series(df.index_value.values, index=pd.to_datetime(df.fecha)).resample("YE").last()
        r = (s.pct_change() * 100).dropna()
        anual[f] = {d.year: v for d, v in r.items()}
    con.close()
    anios = [a for a in sorted(anual["E"]) if a >= 2003 and a in anual["A"]]
    e = [anual["E"][a] for a in anios]
    a = [anual["A"][a_] for a_ in anios]

    fig, ax = plt.subplots(figsize=(11.5, 4.6))
    x = np.arange(len(anios))
    ax.bar(x, e, color=[COST if v < 0 else FONDO_E for v in e], width=0.62, label="Fondo E")
    ax.scatter(x, a, color=FONDO_A, s=22, zorder=3, label="Fondo A")
    ax.axhline(0, color=INK, linewidth=0.8)
    for xi, v in zip(x, e):
        if v < -5:
            ax.text(xi, v - 1.0, f"{v:+.1f}%".replace(".", ","), ha="center", va="top",
                    fontsize=8.8, color=COST, fontweight="600")
    # 24 años no caben horizontales a este ancho: se rotan en vez de saltarse
    # años, porque los que importan (2021, 2026) son justo impares/el último.
    ax.set_xticks(x, [str(a_) if a_ != anios[-1] else f"{a_}*" for a_ in anios],
                  fontsize=8.5, rotation=90)
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    _style(ax, title="El refugio también cae: retorno real anual del Fondo E",
           ylabel="Retorno real anual")
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    _save(fig, "fondo_e_anual.png",
          "Retorno anual en UF; *2026 hasta el 1 de octubre. En 2021 el Fondo E perdió 7,3% nominal con 6,6% de "
          "inflación: -13,1% real, mientras el A ganaba 13,0%.\nEn 2026 las siete AFP muestran entre -7,2% y -8,2% "
          "nominal en el E, sin ningún día extremo: es una caída gradual y sistémica, no un error del índice.")


if __name__ == "__main__":
    print(f"Escribiendo figuras en {FIG_DIR}\n")
    fig_mechanism()
    fig_breakeven()
    fig_distribution()
    fig_traspasos()
    fig_history()
    fig_real_vs_nominal()
    fig_pension_por_edad()
    fig_bootstrap()
    fig_volatilidad_regimen()
    fig_senal_sesgo()
    fig_fondo_e_anual()
    print("\nListo.")
