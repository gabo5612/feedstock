# feedstock

A **local-first** platform for input-cost risk in a metals plant. It ingests raw prices,
normalises them, derives features, forecasts with an honest walk-forward backtest and
serves the result live — **all running inside the plant**.

**What it is NOT:** a trading bot. It does not promise to beat the market. The defensible
claim is *"here is each model's out-of-sample error against the naive baseline, measured
and reproducible"*.

## Status: M2 of 6

| Milestone | | |
|---|---|---|
| **M0** | Docker + Timescale + pgvector | ✅ |
| **M1** | Ingestion + 10-year backfill, 12 instruments | ✅ |
| **M2** | Features + **leakage guard in CI** | ✅ |
| M3 | Backtest + naive baseline published first | ⬜ |
| M4 | ARIMA + LightGBM against the baseline | ⬜ |
| M5 | Anomalies + regime + dashboard | ⬜ |
| M6 | Ollama with citations + offline compose | ⬜ |

## The cost basket

Define a product's real mix (*"340 kg of copper, 120 of aluminium, 0.8 MWh"*) and the
dashboard stops showing generic prices and starts showing **your unit cost**.

Measured on the example mix: cost rose **+47.8% in a year**, and **92.2% depends on
copper** — hedging gas (0.1%) would change nothing.

Units are converted explicitly and **fail loudly** on anything unknown: an implicit kg↔lb
conversion would give a cost 2.2× wrong without raising any error. The troy ounce (31.1 g)
is kept separate from the common one (28.35 g) because confusing them puts a 10% error into
gold and silver.

## Is now a good time to buy?

**It does not predict the price.** It says where the price sits today relative to its own
history and **what happened afterwards the previous times it sat there**, against the
baseline of buying without looking.

The result, measured over 10 years and published as-is: **intuition does not hold, and on
several instruments it is inverted.**

| instrument | band | n | edge |
|---|---|---|---|
| copper | very_cheap | 286 | **−1.8** |
| aluminium | very_cheap | 641 | **+3.3** |
| natgas | cheap | 505 | **−4.9** |
| natgas | very_expensive | 384 | **+5.7** |

Buying copper cheap did *worse* than buying on any random day. On gas it is inverted. Only
aluminium behaves the way common sense says it should.

The cut points are quintiles chosen **before** running the backtest, and they were not moved
afterwards. The panel shows the measured edge next to the band, and its colour is decided by
the evidence: a "very cheap" band with a negative edge is painted red.

## Dashboard

```bash
.venv/bin/python -m uvicorn feedstock.api.main:app --port 8090
# open http://127.0.0.1:8090
```

Search by name, filter by asset class, pick up to 8 instruments and compare. **It is served
by the same process that reads the database:** no external service, no telemetry, and it
works in a plant with no internet. No frontend dependencies — the charts are hand-written
SVG.

Three decisions about reading, not about looks:

- **Indexed comparison at base 100, never a dual axis.** Copper trades near 6.7 USD/lb and
  gold near 4,477 USD/oz. Overlaying them on different scales makes two lines cross because
  of how the chart was drawn, not because of what the prices did.
- **Correlation is over daily returns, not prices.** Two trending series correlate highly
  even when unrelated — the classic trap of this calculation.
- **Eight series is the ceiling**, because that is what the palette validates. A ninth
  colour is not invented: the selection is trimmed.

## Running it

```bash
docker-compose up -d                    # Timescale + pgvector on :5434
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/backfill.py    # all 12 instruments, 10 years
.venv/bin/python -m pytest
```

## What is ingested (measured 2026-09-06)

**30,302 rows · 12 instruments · 0 errors · 0 gaps · 2016-09 → 2026-09**

Each instrument holds ~2,514 daily candles over 10 years. Re-ingestion verified idempotent:
running the backfill again over the same range inserts **0 rows**.

## Two things everything else rests on

### 1. `ZN=F` is not zinc

It is the 10-year Treasury note future, and Yahoo returns it without any error at all.
Putting it in a metals dataset would contaminate the whole thing **without a single signal
that anything is wrong**, and a model trained on top would produce perfectly plausible and
perfectly false numbers.

So every instrument declares an `expect_name` that **must** appear in the name the source
returns, and the check runs **before a single row is written**:

```
zinc: ticker 'ZN=F' returns '10-Year T-Note Futures,Dec-2026', which does not contain
'Zinc'. NOTHING was ingested.
```

### 2. `range=max` lies silently

`range=max&interval=1d` **does not return daily data**: Yahoo downsamples it to monthly
without saying so. Verified twice on copper:

| request | points over 10 years |
|---|---|
| `range=max&interval=1d` | **268** |
| paginated `period1`/`period2` | **2,515** |

A backfill built with `range=max` produces a dataset that *looks* complete and is not. Hence
the adapter paginates in chunks.

## Architecture

Four layers, and the split is not cosmetic:

- **`raw`** — append-only and sacred. PK `(source, symbol, interval, ts)` → idempotent
  re-ingestion. Never modified.
- **`core`** — normalised, gaps flagged. **Rebuilt** from `raw`: if a normalisation turns
  out to be wrong, it is corrected without asking the source for anything again — a source
  that may well have changed or disappeared.
- **`feat`** — versioned. Two predictions are only comparable if they share a
  `feature_version`.
- **`model`** — `run`, `prediction`, `metric`.

Ingestion only ever talks to `SourceAdapter`. Switching to a paid feed — or to real LME
data — means writing a class, not rewriting the system. That is what makes it honest to use
Yahoo's chart API, which is unofficial and carries no service contract.
