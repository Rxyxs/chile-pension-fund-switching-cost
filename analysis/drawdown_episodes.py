"""Finds every real drawdown episode (peak -> trough -> full recovery) in a
fund's daily index, instead of relying on a hand-picked list of "famous"
crises.

A hand-picked list has an obvious bias: it only includes crises someone
remembered to name (GFC, COVID, ...), which tends to overrepresent dramatic,
well-known events and silently drop quieter or less-famous drawdowns that a
real saver still lived through. Scanning the real daily index directly finds
every episode past a chosen severity threshold, whether or not it made the
news.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb


@dataclass(frozen=True)
class DrawdownEpisode:
    fondo: str
    peak_date: date
    peak_value: float
    trough_date: date
    trough_value: float
    recovery_date: date | None  # None if the fund had not recovered to peak_value by the end of the data
    max_drawdown_pct: float


def find_drawdown_episodes(
    con: duckdb.DuckDBPyConnection, fondo: str, threshold_pct: float = 15.0
) -> list[DrawdownEpisode]:
    """Walks the fund's daily index chronologically and returns one
    DrawdownEpisode per contiguous underwater period whose max drawdown
    reaches at least `threshold_pct`. An episode spans from the pre-decline
    peak to the date the index first closes at or above that same peak value
    again (a full recovery) -- intermediate bounces that don't fully recover
    stay inside the same episode, which is the standard definition (a new
    episode only starts once a new all-time-since-last-peak high is made).
    If the fund is still underwater at the end of the data, the trailing
    episode is returned with `recovery_date=None`.
    """
    rows = con.execute(
        "SELECT fecha, index_value FROM fund_index WHERE fondo = ? ORDER BY fecha", [fondo]
    ).fetchall()
    if not rows:
        return []

    episodes: list[DrawdownEpisode] = []
    peak_date, peak_value = rows[0]
    trough_date, trough_value = rows[0]
    in_drawdown = False

    for fecha, value in rows[1:]:
        if not in_drawdown:
            if value > peak_value:
                peak_date, peak_value = fecha, value
                continue
            drawdown_pct = (1 - value / peak_value) * 100
            if drawdown_pct >= threshold_pct:
                in_drawdown = True
                trough_date, trough_value = fecha, value
        else:
            if value < trough_value:
                trough_date, trough_value = fecha, value
            if value >= peak_value:
                episodes.append(
                    DrawdownEpisode(
                        fondo=fondo,
                        peak_date=peak_date,
                        peak_value=peak_value,
                        trough_date=trough_date,
                        trough_value=trough_value,
                        recovery_date=fecha,
                        max_drawdown_pct=round((1 - trough_value / peak_value) * 100, 2),
                    )
                )
                in_drawdown = False
                peak_date, peak_value = fecha, value

    if in_drawdown:
        episodes.append(
            DrawdownEpisode(
                fondo=fondo,
                peak_date=peak_date,
                peak_value=peak_value,
                trough_date=trough_date,
                trough_value=trough_value,
                recovery_date=None,
                max_drawdown_pct=round((1 - trough_value / peak_value) * 100, 2),
            )
        )

    return episodes
