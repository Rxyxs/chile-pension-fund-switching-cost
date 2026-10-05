[ 🇺🇸 English ] | [ 🇨🇱 [Leer en Español](README.es.md) ]

[![tests](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml/badge.svg)](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml)

# chile-pension-fund-switching-cost

What does it actually cost a Chilean saver to panic-switch pension funds during a crash? This project answers that with **real daily data** from the Superintendencia de Pensiones (2002-2026, ~278,000 rows), not a simulated market.

**If you're new to the Chilean pension system**: every worker's mandatory retirement savings sit in one of 5 "multifondos" (funds A through E) managed by a pension fund administrator (an AFP). Fondo A invests up to 80% in stocks — higher expected return, bigger swings. Fondo E invests almost entirely in bonds — lower expected return, much smaller swings. Savers are allowed to switch funds whenever they want, and the popular move during a crash is to flee from A (or B/C) into the "safer" E — this project measures whether that instinct actually pays off.

## The real data — and what "patrimonio-weighted" means

The Superintendencia de Pensiones publishes two numbers every business day, for every AFP, for each of the 5 fund types:

- **`valor cuota`** (unit price): think of each fund as being divided into millions of tiny "shares." This is the price of one share that day. It only tells you the *return* of that AFP's fund — you can't compare the raw number between two AFPs, because each one starts its own share price at CLP 10,000 whenever the fund is created.
- **`valor patrimonio`** (total assets under management): how much money, in total, that AFP's fund holds that day.

This data isn't exposed as a clean API — it's a `.php` export endpoint behind a form on `spensiones.cl/apps/valoresCuotaFondo/` that returns a semicolon-delimited text file. `etl/fetch_valor_cuota.py` reproduces that request in plain Python (no browser, no login needed — anyone can run it).

**A real data-quality trap this project had to solve**: the header row (which AFP sits in which column) *changes* every time an AFP enters, exits, or merges with another — 31 times in Fondo C's file alone, spanning real events like Provida's AFPs consolidating, AFP Modelo's 2010 launch, and AFP Uno's 2019 launch. If you read this file with a single fixed header (the obvious first approach), everything after the first change silently shifts — you'd end up attributing one AFP's numbers to a different AFP's name, and never know it happened. `etl/parse_valor_cuota.py` re-reads the header every time it repeats and re-anchors which column belongs to which AFP from there — this exact scenario is what `tests/test_parse_valor_cuota.py` checks with a small synthetic file built to change its header mid-stream.

**Why "patrimonio-weighted"?** Since each AFP's `valor cuota` is its own independent series, you can't just average the raw prices across AFPs to get "the return of Fondo A" — averaging prices from series that started at different points and grew independently produces a meaningless number. What you *can* do is: compute each AFP's own daily percentage return, then average those returns across AFPs, weighting each one by how much money (`valor patrimonio`) it actually held the day before. That weighting matters — imagine AFP X (managing CLP 9 billion) returns -10% one day, and tiny AFP Y (CLP 1 billion) returns +10% the same day; a simple average of the two returns would say "0%," but that's not what actually happened to the system's money — 90% of the pesos in the system lost 10% that day. `etl/build_duckdb.py` does this weighting, then compounds the resulting daily returns into one index per fund type (starting at 100), which is the standard way index providers (like the ones behind the IPSA or S&P 500) build a benchmark out of many underlying constituents.

## Sanity-checking the index against known history

Before trusting a number I computed, I checked it against two crashes that anyone in the Chilean pension system remembers living through:

| Event | Fondo A drawdown | Fondo E drawdown |
|---|---|---|
| 2008 financial crisis (peak to Nov 2008 trough) | **-30.8%** | +0.4% |
| COVID crash (Feb 20 - Mar 23, 2020) | **-24.6%** | -3.7% |

("Drawdown" here just means: how far did the index fall from its high point to its low point during that crisis, in percent.) Both numbers match the magnitude of those crashes as publicly reported at the time. That Fondo A (up to 80% stocks) dropped ~25-30% while Fondo E (mostly bonds) barely moved isn't a coincidence — it's exactly the risk-profile difference the multifondo system was designed to produce, and seeing the data reproduce it independently is what tells me the index-building logic above is actually correct, not just plausible-looking.

![Fund A vs Fund E, full history](outputs/figures/fondo_a_vs_e_historia.png)

Log scale, patrimonio-weighted index, base 100 at each fund's earliest available date. Fondo C and E have data back to 2002-01-02 (the original pre-reform single-fund lineage); A, B and D start 2002-09-28, when the 2002 multifondo reform actually split the system into five funds. The three dashed lines mark the crisis windows analyzed below — 2008 and 2020 show up as sharp, visible drops in Fondo A that Fondo E barely registers; 2022 is a slower grind that both funds feel.

**Interactive version**: `outputs/figures/*.png` above are static; running `python scripts/make_interactive_dashboard.py` builds `outputs/interactive/pension_switching_dashboard.html` — open it in any browser to zoom into a specific crash, hover over any day for its exact index value, and hover over each panic-switch bar below for its underlying "stay" vs. "panic" numbers. It's gitignored (not committed) because the underlying JSON payload for ~9,000 days × 2 funds makes the file large; regenerating it locally takes a few seconds once the pipeline below has run once.

## The panic-switch counterfactual

A "counterfactual" here just means: I take two different decisions a saver could have made on the *same* real days, using the *same* real index values, and compare where each one ends up. Nothing is simulated or assumed about the market — only the two decisions are hypothetical.

- **STAY**: money stays in Fondo A the entire window — the do-nothing baseline.
- **PANIC**: money moves from A to E at the crash's trough (the lowest point) — not at the first sign of trouble, because that's not when people actually react. Real switching spikes *after* the drop is already realized and painful, once account statements show the loss, which is closer to the trough than the peak. The money then moves back to A only `N` months later, once the recovery has largely already happened without it.

| Scenario | Stay in A | Panic-switch (A→E→A) | Cost of panic |
|---|---|---|---|
| GFC 2008, returns after 12mo | -4.5% | -28.7% | **24.2 pts** |
| COVID 2020, returns after 6mo | +20.3% | +8.3% | **12.0 pts** |
| COVID 2020, returns after 12mo | +32.2% | +6.3% | **25.9 pts** |
| 2022 rate-hike shock, returns after 12mo | +5.6% | +5.5% | **0.1 pts** |

("Cost of panic," in points, is just the STAY percentage minus the PANIC percentage — e.g. in the first row, staying lost 4.5%, but panicking lost 28.7%, a **24.2 percentage-point** gap between the two choices over the same 2 years.)

![Why switching at the trough costs](outputs/figures/mecanismo_covid.png)

The mechanism, on the 2020 crash. Fund A falls 23% and Fund E barely moves — which is
exactly why fleeing feels right at that moment. The cost is not paid on the day of the
switch: it is paid over the following year, when Fund A climbs back to +15% and Fund E
ends roughly where it started. You materialise the fall and then sit out the recovery.

![Distribution of the 15 systematic scenarios](outputs/figures/distribucion_escenarios.png)

**Honest finding, not cherry-picked**: the 2022 scenario shows almost no cost, and I want to be upfront that this wasn't filtered out to make the story cleaner — it's the same methodology applied to a fourth real period, and it happens to disagree with the other three. Here's why, in plain terms: 2022's crisis was a slow, grinding repricing driven by rising interest rates and inflation, not a sharp drop-then-bounce. Bonds (what Fondo E mostly holds) *also* sold off that year because rising rates hurt bond prices too — so fleeing to E didn't actually dodge much pain, and because Fondo A never staged a sharp V-shaped recovery afterward, there was no missed rebound to pay for either. The takeaway isn't "panic-switching always costs ~25 points" — it's that the cost is specific to a certain *shape* of crisis (a sharp fall followed by a sharp recovery), which is exactly what 2008 and COVID were, and what 2022 wasn't.

## Beyond 4 examples: every real crash the data actually contains

The four scenarios above were picked because they're the crises anyone who lived through them remembers by name — and that's a real form of selection bias: a hand-picked list only contains crises someone thought to name, and tends to overrepresent dramatic, well-known ones. `analysis/drawdown_episodes.py` removes the human from that step: it scans the full 2002-2026 Fondo A index programmatically for every period where the index fell at least 15% from a prior peak and later fully recovered, no memory of "famous crashes" required.

It found exactly 3:

| Peak | Trough | Real drawdown | Recovered |
|---|---|---|---|
| 2007-10-31 | 2008-11-21 | -43.2% | 2010-11-05 |
| 2011-01-06 | 2011-10-05 | -17.3% | 2013-01-30 |
| 2020-02-24 | 2020-03-24 | -26.5% | 2020-11-25 |

Notably, the 2022 rate-hike period from the table above is **not** in this list — it never crossed a 15% drawdown by this measure, which is consistent with (not contradicting) the near-zero panic cost already found for it above: a crisis that was never a sharp drawdown in the first place doesn't create much of a "trough" to panic-sell into.

`analysis/systematic_panic_switch_cost.py` then tests each of these 3 real episodes against a grid of 5 realistic return lags (3/6/12/18/24 months) — 15 scenarios total, not 4 — and reports the distribution instead of individual anecdotes:

```bash
python analysis/systematic_panic_switch_cost.py     # -> reports/systematic_panic_switch_results.csv
```

| | Value |
|---|---|
| Scenarios | 15 (3 real episodes × 5 return lags) |
| Mean cost of panic | **+17.15 pts** |
| Median cost of panic | +12.19 pts |
| Std. dev. | 10.05 pts |
| Range | +1.53 to +36.51 pts |
| Panic worse than staying | **100%** of scenarios |
| Panic better than staying | 0% of scenarios |

Every one of the 15 systematic scenarios favored staying — not just the 3 headline crashes, across every return lag tested. That's a stronger, more mechanically-derived version of the same conclusion the 4 hand-picked scenarios pointed to, not a different one — but now it's backed by every qualifying real crash in the dataset instead of a curated four. Full per-scenario numbers in `reports/systematic_panic_switch_results.csv`; aggregate numbers in `reports/systematic_panic_switch_summary.json`.

## "And what if I had moved *earlier*?" — where the advice flips

Everything above fixes the switch **at the trough**, which is what panic means: you flee
after the fall has already happened. But a reasonable reader asks the obvious follow-up —
*what if I had moved when it had only dropped a little?*

`analysis/timing_grid.py` answers it, with one design decision that does the real work.

**The variable is not the calendar, it is the loss already suffered.** Sweeping by "days
before the trough" produces a result that is true and useless: switching a week after the
2007 peak wins by 90 points, because it dodges the entire crash. But nobody knows they are
standing on the peak — that combination measures foresight, not panic. What a person *can*
observe on the day they decide is how much they have lost so far. So the grid is indexed by
drawdown-at-switch, which turns the question into an actionable one: **if I have already
lost X%, does moving still help?**

481 combinations of (switch day × return lag) across the 3 real drawdowns:

![Where switching stops helping](outputs/figures/punto_de_quiebre.png)

| Loss already suffered when switching | n | Median cost of switching | Switching wins |
|---|---:|---:|---:|
| 0% to −5% | 145 | **−14.0 pp** | 100% |
| −5% to −10% | 123 | **−18.2 pp** | 94% |
| −10% to −20% | 159 | **−10.1 pp** | 74% |
| −20% to −30% | 19 | **+2.9 pp** | 42% |
| more than −30% | 35 | **+16.2 pp** | 29% |

**The break-even sits around −25% of loss already taken.** Below it, moving still helped in
these crashes; past it, it cost — and the original trough-anchored analysis is simply the
extreme case of that last row, since switching at the trough means switching having
absorbed 100% of the fall.

Three caveats, because this result is easy to misread:

- **It is not a strategy.** A region where switching wins is not a region you can occupy:
  winning there requires knowing the fall will continue, which is exactly what is unknown
  at the time. The threshold is useful in the other direction — telling someone who has
  already lost a lot that moving now will not save them.
- **Three episodes, not three thousand.** The percentages describe these crises. The
  −20% to −30% bucket rests on 19 combinations drawn from the same handful of crashes, so
  the 42% there carries far less weight than the 100% in the first row.
- **The buckets are not independent observations.** Combinations within one episode share
  the same market path, so the effective sample is closer to 3 than to 481.

## Calculate your own scenario

`scripts/calculator.py` is an interactive command-line calculator: pick one of the real detected drawdown episodes above (or type your own dates), choose which fund you'd panic-switch into and how many months before you'd move back, and it computes the real historical cost against the same data as everything above — not a rule of thumb.

```bash
python scripts/calculator.py
```

## Does real switching behavior actually spike near the trough?

Everything above answers "what would it cost if someone panic-switched" — it's a price-only counterfactual, not evidence that people actually do this. So I went looking for the real behavior: the Superintendencia de Pensiones publishes a monthly bulletin (`Ficha Estadística Previsional`, one PDF per month, 164 issues archived back to Dec 2012) that reports, with a 2-month lag, the real system-wide count of accounts transferred between AFPs that month. I pulled 22 of these bulletins — covering a pre-COVID baseline (mid-2019) plus the full COVID window (2020) and the 2022 rate-hike window — and extracted that one real number from each.

**A second real data-quality trap, in the source PDFs themselves**: the table (`Tabla N° 7`) that reports this number has a footnote written in prose — *"...traspasadas entre AFP en agosto de 2020 fue de..."* — and in at least two of the 22 bulletins checked, that prose names the wrong month (off by a month, in one case off by a year) relative to what the table's own column headers say. `etl/parse_traspasos.py` doesn't trust the footnote's prose for the month — it derives the month from the table's header row instead (which is corroborated by every other column on the same table), and only takes the transfer count itself from the footnote. `tests/test_parse_traspasos.py` locks in this exact bug with a synthetic fixture reproducing it.

![Real monthly transfer volume between AFPs](outputs/figures/traspasos_volumen.png)

**This is the honest surprise of the whole project**: transfer volume does *not* spike at the COVID trough — it *collapses*, from ~53,000 accounts/month in early 2020 down to just 15,618 in May 2020, before rebounding sharply to ~50,000 in October 2020. That's not evidence people weren't panicking — Chile was under strict lockdown from late March 2020, AFP branch visits were restricted, and part of the transfer process wasn't fully digital yet at the time, so the collapse is confounded with people's literal inability to process a switch, not proof they didn't want to. The October 2020 rebound lines up with lockdown easing and with the political controversy around the first pension-fund withdrawal law (passed July 2020) putting AFPs in the daily news — plausibly a bigger behavioral trigger than the March crash itself. The 2022 window, by contrast, shows no dramatic move around the October trough at all — consistent with the ~0-point panic cost found for that scenario above: if switching barely would have cost anything, there's little reason to expect a spike in switching either.

Net: the price-side story (panic-switching a sharp V-shaped crash is expensive) holds up well. The behavior-side story (people rush into safety exactly at the trough) does not hold up cleanly in this data — the real pattern in 2020 looks more like "couldn't move, then moved once things reopened" than "panicked at the bottom."

## Reproduce it

```bash
pip install -r requirements.txt
python etl/fetch_valor_cuota.py            # downloads the 5 real source files (~7MB)
python etl/parse_valor_cuota.py            # -> data/processed/valor_cuota_long.parquet
python etl/fetch_fichas.py                 # downloads 22 real monthly bulletin PDFs
python etl/parse_traspasos.py              # -> data/processed/traspasos_monthly.parquet
python etl/build_duckdb.py                 # -> data/pension_funds.duckdb
python analysis/panic_switch_cost.py       # -> reports/panic_switch_results.csv
python analysis/systematic_panic_switch_cost.py  # -> reports/systematic_panic_switch_results.csv + summary.json
python analysis/timing_grid.py             # -> reports/timing_grid.csv
python scripts/make_charts.py              # -> outputs/figures/*.png
python scripts/make_interactive_dashboard.py  # -> outputs/interactive/*.html (not committed, see above)
python scripts/calculator.py               # interactive: your own panic-switch scenario
pytest tests/ -v                           # 29 tests, no network needed (synthetic fixtures)
```

## Next steps

The 22-bulletin window covers COVID and 2022 but not the 2008 GFC (the bulletin series only starts Dec 2012) — the price-side GFC finding above has no behavior-side counterpart to check it against. A logical follow-up: extend the transfer-volume series further, and split it by origin/destination fund (`Tabla N° 5`, not yet extracted) to see whether the money that did move in 2020 went where the panic story would predict — toward Fondo E — or somewhere else entirely.

## Author

Pablo Reyes — Data Scientist, Santiago, Chile.

License: MIT — see [LICENSE](LICENSE).
