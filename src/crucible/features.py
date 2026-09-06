"""Features. All causal, and there is a test that proves it.

**The rule governing this entire file:** a feature at `ts` may only use data with a
timestamp <= `ts`. Not one later, not even `ts`'s own close when the feature claims to be
available *before* the close.

Look-ahead bias is what makes 95% of price-prediction projects garbage with beautiful
charts: someone computes a centred moving average, or normalises with the whole series'
mean, and the model "predicts" using information that did not exist at that moment. The
result looks spectacular and cannot be reproduced live even once.

Here every window looks backwards (`rows BETWEEN n PRECEDING AND CURRENT ROW`) and the guard
in `tests/test_leak.py` verifies it independently: it recomputes each feature truncating the
series at each `origin_ts` and requires the same value. If one looks ahead, the truncated
version differs and the test fails.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")

# Changes when a feature's DEFINITION changes, not when rows are added. Two predictions are
# only comparable if they share this version: without it, a change of definition turns a
# comparison into a coincidence.
FEATURE_VERSION = "v1"

# Windows in market business days.
WINDOWS = (20, 60, 252)


@dataclass
class FeatureReport:
    symbol: str
    rows: int
    names: tuple[str, ...]


# Every window is `n PRECEDING AND CURRENT ROW`: backwards, including today.
# A centred window (`n PRECEDING AND n FOLLOWING`) would be pure leakage.
SQL_FEATURES = """
WITH base AS (
  SELECT symbol, ts, close,
         ln(close / lag(close) OVER w) AS ret
    FROM core.bar
   WHERE symbol = %(symbol)s AND interval = '1d' AND close > 0
  WINDOW w AS (PARTITION BY symbol ORDER BY ts)
),
calc AS (
  SELECT symbol, ts, close, ret,
         avg(close) OVER w20  AS sma_20,
         avg(close) OVER w60  AS sma_60,
         stddev_samp(ret) OVER w20  * sqrt(252) AS vol_20,
         stddev_samp(ret) OVER w60  * sqrt(252) AS vol_60,
         min(close) OVER w252 AS min_252,
         max(close) OVER w252 AS max_252,
         avg(close) OVER w252 AS sma_252,
         stddev_samp(close) OVER w252 AS sd_252,
         -- Percentile rank within its own recent history: 0 = the cheapest of the last
         -- 252 business days, 1 = the most expensive. This is the basis of the buy
         -- signal, and it is a DESCRIPTION of the present, not a forecast.
         percent_rank() OVER (PARTITION BY symbol ORDER BY ts
                              ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS _ignorado
    FROM base
  WINDOW w20  AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
         w60  AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
         w252 AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
)
SELECT symbol, ts, close, ret, sma_20, sma_60, sma_252, vol_20, vol_60,
       min_252, max_252, sd_252
  FROM calc
 ORDER BY ts
"""


def _derived(row: dict) -> dict[str, float | None]:
    """Features derived from the aggregates. Arithmetic on the same row: it cannot leak."""
    close = row["close"]
    out: dict[str, float | None] = {
        "ret_1d": row["ret"],
        "vol_20d": row["vol_20"],
        "vol_60d": row["vol_60"],
    }
    for n in (20, 60, 252):
        sma = row.get(f"sma_{n}")
        out[f"sma_{n}d"] = sma
        # Relative distance from its mean: how far above or below it sits today.
        out[f"dist_sma_{n}d"] = (close / sma - 1) if sma else None

    lo, hi = row["min_252"], row["max_252"]
    # Position in the 52-week range. 0 = year low, 1 = year high.
    out["pos_rango_252d"] = ((close - lo) / (hi - lo)) if (lo is not None and hi and hi > lo) else None

    sd, mean_ = row["sd_252"], row["sma_252"]
    # Z-score against its own annual history.
    out["z_252d"] = ((close - mean_) / sd) if (sd and mean_ is not None) else None
    return out


def compute(symbol: str, *, dsn: str = DSN, persist: bool = True) -> FeatureReport:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_FEATURES, {"symbol": symbol})
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            records = []
            for f in rows:
                for name, value in _derived(f).items():
                    if value is not None:
                        records.append((symbol, f["ts"], name, float(value), FEATURE_VERSION))

            if persist and records:
                cur.executemany(
                    """INSERT INTO feat.feature (symbol, ts, name, value, feature_version)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (symbol, ts, name, feature_version)
                       DO UPDATE SET value = EXCLUDED.value""",
                    records,
                )
        conn.commit()

    names = tuple(sorted({r[2] for r in records}))
    return FeatureReport(symbol=symbol, rows=len(records), names=names)


def compute_all(symbols, **kw) -> list[FeatureReport]:
    return [compute(s, **kw) for s in symbols]
