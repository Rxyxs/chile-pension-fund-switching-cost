"""¿A partir de cuánta pérdida ya sufrida deja de servir cambiarse?

Los análisis previos de este repositorio fijan el cambio **exactamente en el
piso** de la caída y solo varían el lag de retorno. Eso mide el peor momento
posible, pero deja una pregunta abierta que un lector razonable se hace: *¿y si
me hubiera cambiado antes, cuando recién empezaba a caer?*

Este módulo la responde, con un cuidado que vale declarar de entrada.

**La variable correcta no es el calendario, es la pérdida ya sufrida.** Barrer
por "días antes del piso" produce un resultado tan cierto como inútil: cambiarse
una semana después del techo de 2007 gana 90 puntos, porque esquiva el crash
entero. Pero nadie sabe que está parado en el techo — esa combinación no mide
pánico, mide presciencia. Lo que una persona sí observa el día que decide es
cuánto perdió hasta ahí.

Así que la grilla se indexa por `drawdown_at_switch`: qué tan abajo del máximo
estaba el fondo A el día del cambio. Eso sí es observable en el momento, y
convierte la pregunta en una accionable: **si ya perdiste X%, ¿todavía conviene
moverse?**

Lo que NO es esto: una estrategia. Que exista una región donde cambiarse gana no
significa que se pueda ocupar — requiere saber que la caída va a continuar, que
es exactamente lo que no se sabe. El valor del corte está en la otra dirección:
decirle a alguien que ya perdió mucho que moverse ahora no lo salva.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.drawdown_episodes import find_drawdown_episodes  # noqa: E402
from analysis.panic_switch_cost import _index_on_or_before  # noqa: E402

DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"

FROM_FUND = "A"
TO_FUND = "E"

# Paso semanal: el valor cuota es diario, pero un traspaso tarda días hábiles en
# hacerse efectivo, así que una grilla más fina simularía una precisión de
# ejecución que no existe.
STEP_DAYS = 7

# Horizonte fijo después de la recuperación, igual para todas las combinaciones,
# para que ninguna se beneficie de haber sido medida más tarde.
HORIZON_DAYS_AFTER_RECOVERY = 365

# Retornos a evaluar, en meses después del cambio. Se acotan a plazos que una
# persona podría sostener: volver "cuando se recupere" sin plazo es otra forma
# de presciencia.
RETURN_LAGS_MONTHS = (3, 6, 12, 18, 24)


@dataclass(frozen=True)
class GridPoint:
    episode: str
    peak_date: date
    trough_date: date
    switch_date: date
    return_date: date
    drawdown_at_switch_pct: float      # lo que ya había perdido al cambiarse
    share_of_fall_elapsed: float       # qué fracción de la caída total ya había ocurrido
    return_lag_months: int
    stay_growth_pct: float
    switch_growth_pct: float
    cost_of_switching_pct_pts: float

    @property
    def switching_won(self) -> bool:
        return self.cost_of_switching_pct_pts < 0


def simulate_at(
    con: duckdb.DuckDBPyConnection,
    entry_date: date,
    switch_date: date,
    return_date: date,
    exit_date: date,
    from_fund: str = FROM_FUND,
    to_fund: str = TO_FUND,
) -> tuple[float, float]:
    """Crecimiento de quedarse vs. cambiarse, entre entry_date y exit_date.

    Generaliza `simulate_panic_switch`: allí el cambio ocurre en el piso, acá
    ocurre en `switch_date`, cualquier día de la caída.
    """
    from_at_entry = _index_on_or_before(con, from_fund, entry_date)
    from_at_switch = _index_on_or_before(con, from_fund, switch_date)
    from_at_return = _index_on_or_before(con, from_fund, return_date)
    from_at_exit = _index_on_or_before(con, from_fund, exit_date)
    to_at_switch = _index_on_or_before(con, to_fund, switch_date)
    to_at_return = _index_on_or_before(con, to_fund, return_date)

    stay_value = from_at_exit / from_at_entry
    switch_value = (
        (from_at_switch / from_at_entry)
        * (to_at_return / to_at_switch)
        * (from_at_exit / from_at_return)
    )
    return (stay_value - 1) * 100, (switch_value - 1) * 100


def build_grid(con: duckdb.DuckDBPyConnection, step_days: int = STEP_DAYS) -> list[GridPoint]:
    from dateutil.relativedelta import relativedelta

    episodes = [e for e in find_drawdown_episodes(con, FROM_FUND) if e.recovery_date is not None]
    points: list[GridPoint] = []

    for ep in episodes:
        exit_date = ep.recovery_date + timedelta(days=HORIZON_DAYS_AFTER_RECOVERY)
        peak_value = _index_on_or_before(con, FROM_FUND, ep.peak_date)
        trough_value = _index_on_or_before(con, FROM_FUND, ep.trough_date)
        total_fall = peak_value - trough_value

        d = ep.peak_date + timedelta(days=step_days)
        while d <= ep.trough_date:
            value_at_switch = _index_on_or_before(con, FROM_FUND, d)
            drawdown = (value_at_switch / peak_value - 1) * 100
            share = (peak_value - value_at_switch) / total_fall if total_fall > 0 else 0.0

            for lag in RETURN_LAGS_MONTHS:
                return_date = d + relativedelta(months=lag)
                if return_date > exit_date:
                    continue
                stay, sw = simulate_at(con, ep.peak_date, d, return_date, exit_date)
                points.append(
                    GridPoint(
                        episode=f"{ep.peak_date} → {ep.trough_date} ({ep.max_drawdown_pct:.1f}%)",
                        peak_date=ep.peak_date,
                        trough_date=ep.trough_date,
                        switch_date=d,
                        return_date=return_date,
                        drawdown_at_switch_pct=round(drawdown, 3),
                        share_of_fall_elapsed=round(share, 4),
                        return_lag_months=lag,
                        stay_growth_pct=round(stay, 4),
                        switch_growth_pct=round(sw, 4),
                        cost_of_switching_pct_pts=round(stay - sw, 4),
                    )
                )
            d += timedelta(days=step_days)
    return points


def find_breakeven(df: pl.DataFrame) -> float | None:
    """Pérdida ya sufrida a partir de la cual cambiarse deja de convenir.

    Se busca el último punto de la grilla (ordenada por drawdown creciente en
    magnitud) donde la mediana del costo cruza de negativa a positiva. Se usa la
    mediana y no la media porque la cola de combinaciones muy tempranas la
    arrastra.
    """
    by_bucket = (
        df.with_columns((pl.col("drawdown_at_switch_pct") / 2.5).round() * 2.5)
        .group_by("drawdown_at_switch_pct")
        .agg(pl.col("cost_of_switching_pct_pts").median().alias("median_cost"))
        .sort("drawdown_at_switch_pct", descending=True)  # de 0% hacia -40%
    )
    rows = by_bucket.to_dicts()
    for prev, cur in zip(rows, rows[1:]):
        if prev["median_cost"] < 0 <= cur["median_cost"]:
            return cur["drawdown_at_switch_pct"]
    return None


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    points = build_grid(con)
    con.close()

    df = pl.DataFrame([p.__dict__ for p in points])
    out = REPORTS_DIR / "timing_grid.csv"
    df.write_csv(out)

    costs = df["cost_of_switching_pct_pts"]
    won = int((costs < 0).sum())
    total = len(df)

    print(f"Grilla de timing sobre {df['episode'].n_unique()} caídas reales de Fondo A")
    print(f"  combinaciones (día del cambio × lag de retorno): {total:,}")
    print()
    print(f"  costo medio de cambiarse : {costs.mean():+.2f} pp")
    print(f"  mediana                  : {costs.median():+.2f} pp")
    print(f"  cambiarse gana en        : {won:,}/{total:,} ({won/total:.1%}) de las combinaciones")
    print()
    print("  Pero el promedio esconde lo único que importa acá. Partido por cuánto")
    print("  se había perdido YA al momento de cambiarse:")
    print()

    buckets = [(0, -5), (-5, -10), (-10, -20), (-20, -30), (-30, -100)]
    print(f"  {'pérdida ya sufrida':<22} {'n':>6} {'costo mediano':>15} {'gana cambiarse':>16}")
    for hi, lo in buckets:
        sub = df.filter(
            (pl.col("drawdown_at_switch_pct") <= hi) & (pl.col("drawdown_at_switch_pct") > lo)
        )
        if sub.is_empty():
            continue
        w = int((sub["cost_of_switching_pct_pts"] < 0).sum())
        label = f"{hi}% a {lo}%" if lo > -100 else f"más de {-hi}%"
        print(f"  {label:<22} {len(sub):>6} {sub['cost_of_switching_pct_pts'].median():>+14.2f} pp"
              f" {w/len(sub):>15.0%}")

    be = find_breakeven(df)
    print()
    if be is not None:
        print(f"  Punto de quiebre: alrededor de {be:.1f}% de pérdida ya sufrida,")
        print("  cambiarse deja de convenir en mediana y empieza a costar.")
    else:
        print("  No se detecta un cruce limpio en la mediana.")

    print()
    print("  Advertencia que acompaña a este resultado: que exista una región donde")
    print("  cambiarse gana NO la vuelve ocupable. Ganar ahí exige saber que la caída")
    print("  va a seguir, que es justo lo que no se sabe. El corte sirve al revés:")
    print("  para decirle a alguien que ya perdió mucho que moverse ahora no lo salva.")
    print(f"\n-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
