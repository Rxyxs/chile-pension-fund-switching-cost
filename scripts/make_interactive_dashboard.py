"""Builds a self-contained interactive Plotly dashboard (offline HTML) from the real
patrimonio-weighted fund index (etl/build_duckdb.py) and the panic-switch results
(analysis/panic_switch_cost.py). No fabricated data -- both come from an actual run.

Output: outputs/interactive/pension_switching_dashboard.html
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pension_funds.duckdb"
RESULTS_PATH = ROOT / "reports" / "panic_switch_results.csv"
OUT_DIR = ROOT / "outputs" / "interactive"

CRISIS_MARKERS = [
    ("GFC 2008", "2008-11-20"),
    ("COVID 2020", "2020-03-23"),
    ("Alza de tasas 2022", "2022-10-20"),
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    idx = con.execute(
        "SELECT fondo, fecha, index_value FROM fund_index WHERE fondo IN ('A','E') ORDER BY fondo, fecha"
    ).fetchdf()
    traspasos = con.execute(
        "SELECT data_month, total_traspasos FROM traspasos_monthly ORDER BY data_month"
    ).fetchdf()
    con.close()
    traspasos["fecha"] = pd.to_datetime(traspasos["data_month"] + "-01")

    results = pd.read_csv(RESULTS_PATH)

    fig = make_subplots(
        rows=3,
        cols=1,
        row_heights=[0.46, 0.28, 0.26],
        vertical_spacing=0.09,
        subplot_titles=(
            "Índice de rentabilidad real ponderado por patrimonio — Fondo A vs. Fondo E (2002-2026)",
            "Costo real de cambiarse en pánico (A → E → A) por escenario",
            "N° real de cuentas traspasadas entre AFP por mes (¿se dispara en el valle?)",
        ),
    )

    for fondo, color in [("A", "#c0392b"), ("E", "#2980b9")]:
        sub = idx[idx["fondo"] == fondo]
        fig.add_trace(
            go.Scatter(
                x=sub["fecha"], y=sub["index_value"], name=f"Fondo {fondo}",
                line=dict(color=color, width=1.3),
                hovertemplate="%{x|%Y-%m-%d}<br>Índice: %{y:.1f}<extra>Fondo " + fondo + "</extra>",
            ),
            row=1, col=1,
        )

    for label, x in CRISIS_MARKERS:
        fig.add_vline(x=x, line_dash="dash", line_color="grey", opacity=0.5, row=1, col=1)
        fig.add_annotation(
            x=x, y=1.0, yref="y domain", text=label, showarrow=False,
            textangle=-90, font=dict(size=10, color="grey"), xanchor="right", row=1, col=1,
        )

    fig.update_yaxes(type="log", title_text="Índice (base 100, escala log)", row=1, col=1)

    bar_colors = ["#c0392b" if v > 5 else "#7f8c8d" for v in results["cost_of_panic_pct_pts"]]
    fig.add_trace(
        go.Bar(
            x=results["cost_of_panic_pct_pts"], y=results["scenario"], orientation="h",
            marker_color=bar_colors, showlegend=False,
            customdata=results[["stay_growth_pct", "panic_growth_pct"]].values,
            hovertemplate=(
                "%{y}<br>Se queda: %{customdata[0]:.1f}%<br>Pánico: %{customdata[1]:.1f}%"
                "<br>Costo: %{x:.1f} pts<extra></extra>"
            ),
        ),
        row=2, col=1,
    )
    fig.update_xaxes(title_text="Puntos porcentuales de rentabilidad perdida", row=2, col=1)

    fig.add_trace(
        go.Scatter(
            x=traspasos["fecha"], y=traspasos["total_traspasos"], mode="lines+markers",
            line=dict(color="#2c3e50", width=1.4), marker=dict(size=5), showlegend=False,
            hovertemplate="%{x|%Y-%m}<br>%{y:,.0f} cuentas traspasadas<extra></extra>",
        ),
        row=3, col=1,
    )
    for label, x in [("Trough COVID", "2020-03-23"), ("Trough alza tasas", "2022-10-20")]:
        fig.add_vline(x=x, line_dash="dash", line_color="#c0392b", opacity=0.6, row=3, col=1)
    fig.update_yaxes(title_text="N° cuentas traspasadas", row=3, col=1)

    fig.update_layout(
        height=1150,
        template="plotly_white",
        title_text="Costo real de cambiarse de fondo en pánico — datos reales SP (2002-2026)",
        margin=dict(l=10, r=10, t=90, b=10),
    )

    out_path = OUT_DIR / "pension_switching_dashboard.html"
    fig.write_html(out_path, include_plotlyjs="cdn")
    print(f"-> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
