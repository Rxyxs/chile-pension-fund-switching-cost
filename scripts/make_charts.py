"""Generate the two README figures from the real DuckDB index and the panic-switch results."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"
FIG_DIR = ROOT / "outputs" / "figures"


def fig_full_history() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(
        "SELECT fondo, fecha, index_value FROM fund_index WHERE fondo IN ('A','E') ORDER BY fondo, fecha"
    ).fetchdf()
    con.close()

    fig, ax = plt.subplots(figsize=(11, 5))
    for fondo, color in [("A", "#c0392b"), ("E", "#2980b9")]:
        sub = df[df["fondo"] == fondo]
        ax.plot(sub["fecha"], sub["index_value"], label=f"Fondo {fondo}", color=color, linewidth=1.2)

    for label, x in [
        ("GFC 2008", date(2008, 11, 20)),
        ("COVID 2020", date(2020, 3, 23)),
        ("Alza tasas 2022", date(2022, 10, 20)),
    ]:
        ax.axvline(x, color="grey", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.text(x, ax.get_ylim()[1] * 0.02 + ax.get_ylim()[0], label, rotation=90,
                fontsize=8, color="grey", va="bottom")

    ax.set_title("Índice de rentabilidad real ponderado por patrimonio — Fondo A vs. Fondo E (2002-2026)")
    ax.set_ylabel("Índice (base 100)")
    ax.legend()
    ax.set_yscale("log")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fund_a_vs_e_history.png", dpi=150)
    plt.close(fig)


def fig_panic_cost_bars() -> None:
    df = pl.read_csv(REPORTS_DIR / "panic_switch_results.csv")

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#c0392b" if v > 5 else "#7f8c8d" for v in df["cost_of_panic_pct_pts"]]
    ax.barh(df["scenario"], df["cost_of_panic_pct_pts"], color=colors)
    ax.set_xlabel("Costo del pánico (puntos porcentuales de rentabilidad perdida)")
    ax.set_title("Costo real de pánico: A -> E en la caída, vuelve tarde", fontsize=12)
    ax.axvline(0, color="black", linewidth=0.8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "panic_switch_cost.png", dpi=150)
    plt.close(fig)


def fig_traspasos_volume() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(
        "SELECT data_month, total_traspasos FROM traspasos_monthly ORDER BY data_month"
    ).fetchdf()
    con.close()

    months = pd.to_datetime(df["data_month"] + "-01")

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(months, df["total_traspasos"], marker="o", markersize=4, color="#2c3e50", linewidth=1.4)

    for label, x in [("Trough COVID (23-mar-2020)", date(2020, 3, 23)),
                      ("Trough alza tasas (20-oct-2022)", date(2022, 10, 20))]:
        ax.axvline(x, color="#c0392b", linestyle="--", linewidth=0.9, alpha=0.7)
        ax.text(x, ax.get_ylim()[1], label, rotation=90, fontsize=8, color="#c0392b", va="top", ha="right")

    ax.axvspan(date(2020, 3, 1), date(2020, 9, 1), color="#c0392b", alpha=0.06)
    ax.text(date(2020, 6, 1), ax.get_ylim()[0], "cuarentena estricta", fontsize=8, color="#c0392b",
            ha="center", va="bottom")

    ax.set_title("N° real de cuentas traspasadas entre AFP por mes (Ficha Estadística Previsional, SP)")
    ax.set_ylabel("N° de cuentas traspasadas")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "traspasos_volume.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig_full_history()
    fig_panic_cost_bars()
    fig_traspasos_volume()
    print(f"-> {FIG_DIR.relative_to(ROOT)}")
