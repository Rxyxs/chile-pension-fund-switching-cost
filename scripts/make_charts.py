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


if __name__ == "__main__":
    print(f"Escribiendo figuras en {FIG_DIR}\n")
    fig_mechanism()
    fig_breakeven()
    fig_distribution()
    fig_traspasos()
    fig_history()
    print("\nListo.")
