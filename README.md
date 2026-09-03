[ 🇺🇸 English ] | [ 🇨🇱 [Leer en Español](README.es.md) ]

[![tests](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml/badge.svg)](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml)

# chile-pension-fund-switching-cost

What does it actually cost a Chilean saver to panic-switch pension funds during a crash? This project answers that with **real daily data** from the Superintendencia de Pensiones (2002-2026, ~278,000 rows), not a simulated market.

## The real data

The Superintendencia de Pensiones publishes the daily `valor cuota` (unit price) and `valor patrimonio` (AUM) of every AFP, for each of the 5 multifondos (A = most equity-heavy, E = most conservative), going back to 2002. It's not exposed as a clean API — it's a `.php` export endpoint behind a form (`spensiones.cl/apps/valoresCuotaFondo/`) that returns a semicolon-delimited text file. `etl/fetch_valor_cuota.py` reproduces that request in plain Python (no browser, no auth needed).

**A real data-quality trap this project had to solve**: the header row (which AFPs are in which column) *changes* every time an AFP enters, exits, or merges — 31 times in Fondo C's file alone, spanning real events like Provida's AFPs consolidating, AFP Modelo's 2010 launch, and AFP Uno's 2019 launch. A naive single-header CSV read would silently misalign columns after the first change and mix one AFP's numbers into another's. `etl/parse_valor_cuota.py` re-anchors column positions every time the header repeats — tested in `tests/test_parse_valor_cuota.py` against a synthetic file that changes header mid-stream.

Each AFP's unit price is its own independent series (rebased to CLP 10,000 whenever a fund launches), so raw prices aren't comparable across AFPs. `etl/build_duckdb.py` computes each AFP's daily return, weights it by that AFP's prior-day AUM, and compounds the weighted-average return into one patrimonio-weighted index per fund type — the standard way to build a benchmark index from constituent price series.

## Sanity-checking the index against known history

Before trusting the index for any analysis, I checked it against two crashes everyone in Chile's pension system remembers:

| Event | Fondo A drawdown | Fondo E drawdown |
|---|---|---|
| 2008 financial crisis (peak to Nov 2008 trough) | **-30.8%** | +0.4% |
| COVID crash (Feb 20 - Mar 23, 2020) | **-24.6%** | -3.7% |

Both match the publicly reported magnitude of those crashes. Fondo A (up to 80% equities) dropping ~25-30% while Fondo E (mostly fixed income) barely moves is exactly the risk-profile difference the multifondo system is designed to produce.

![Fund A vs Fund E, full history](outputs/figures/fund_a_vs_e_history.png)

Log scale, patrimonio-weighted index, base 100 at each fund's earliest available date. Fondo C and E have data back to 2002-01-02 (the original pre-reform single fund lineage); A, B and D start 2002-09-28, when the 2002 multifondo reform actually split the system into five funds. The three dashed lines mark the crisis windows analyzed below — 2008 and 2020 show up as sharp, visible drops in Fondo A that Fondo E barely registers; 2022 is a slower grind that both funds feel.

## The panic-switch counterfactual

For each crisis, I compare two real, back-tested paths using only real index levels on real calendar dates — no synthetic assumptions:

- **STAY**: money stays in Fondo A the entire window.
- **PANIC**: money moves from A to E at the crash's trough (empirically, that's closer to when retail switching actually spikes — after the drop is already realized and painful, not before it) and moves back to A only `N` months later, once the recovery has already happened without them.

| Scenario | Stay in A | Panic-switch (A→E→A) | Cost of panic |
|---|---|---|---|
| GFC 2008, returns after 12mo | -4.5% | -28.7% | **24.2 pts** |
| COVID 2020, returns after 6mo | +20.3% | +8.3% | **12.0 pts** |
| COVID 2020, returns after 12mo | +32.2% | +6.3% | **25.9 pts** |
| 2022 rate-hike shock, returns after 12mo | +5.6% | +5.5% | **0.1 pts** |

![Cost of panic-switching by scenario](outputs/figures/panic_switch_cost.png)

**Honest finding, not cherry-picked**: the 2022 scenario shows almost no cost. That's real — 2022's crisis was a slow, grinding repricing driven by rate hikes and inflation, not a sharp V-shaped crash. Bonds (what Fondo E holds most of) sold off too that year, so fleeing to E didn't actually protect anything, and there was no sharp recovery in A to miss. The panic-switch penalty isn't a universal tax — it's specifically the cost of mistiming a sharp crash-and-V-shaped-recovery, which is exactly what 2008 and 2020 were and 2022 wasn't.

## Reproduce it

```bash
pip install -r requirements.txt
python etl/fetch_valor_cuota.py      # downloads the 5 real source files (~7MB)
python etl/parse_valor_cuota.py      # -> data/processed/valor_cuota_long.parquet
python etl/build_duckdb.py           # -> data/pension_funds.duckdb
python analysis/panic_switch_cost.py # -> reports/panic_switch_results.csv
python scripts/make_charts.py        # -> outputs/figures/*.png
pytest tests/ -v                     # 9 tests, no network needed (synthetic fixtures)
```

## Next steps

The panic-switch model assumes a single lump-sum move at the trough — a real affiliate could switch gradually or multiple times (the law caps switches per year, not tracked here). A logical follow-up: extract the monthly switch-volume bulletins (`Compendio de Pensiones`, published as PDF) to check whether real switch volume actually spikes near the troughs this project identified, closing the loop between "what it costs" and "whether people actually do it."

## Author

Pablo Reyes — Data Scientist, Santiago, Chile.

License: MIT — see [LICENSE](LICENSE).
