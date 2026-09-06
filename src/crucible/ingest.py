"""Ingestion: source → raw.ohlcv_ingest → core.bar.

Two properties the rest of the system takes for granted, guaranteed here:

**1. Name verification runs BEFORE a single row is written.** If the name the source returns
does not contain the expected fragment, the whole instrument is rejected. `ZN=F` returns
"10-Year T-Note Futures" and not "Zinc": without this check it would enter as zinc,
contaminate the metals dataset, and there would be **no** signal that anything was wrong. A
model trained on top would produce perfectly plausible and perfectly false numbers.

**2. Re-ingestion is idempotent.** The PK of `raw.ohlcv_ingest` is
(source, symbol, interval, ts) and inserts use ON CONFLICT DO NOTHING. Running the backfill
twice over the same range does not duplicate a row. That is what makes retrying thoughtless.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from .instruments import BY_SYMBOL, Instrument
from .sources import SourceAdapter, SourceError

DSN = os.environ.get(
    "CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible"
)


class VerificationError(RuntimeError):
    """The source's name does not match what was expected. Nothing was written."""


@dataclass
class IngestReport:
    symbol: str
    source_name: str
    bars_fetched: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0        # already present: proof of idempotence
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    gaps: int = 0
    error: str | None = None


def verify_name(adapter: SourceAdapter, inst: Instrument) -> str:
    """Checks the source returns the instrument we think it does. Fails loudly."""
    name = adapter.display_name(inst.source_ticker)
    if inst.expect_name.lower() not in name.lower():
        raise VerificationError(
            f"{inst.symbol}: ticker {inst.source_ticker!r} returns {name!r}, which does not "
            f"contain {inst.expect_name!r}. NOTHING was ingested. If the ticker changed "
            f"meaning, fix the registry; do not relax this check."
        )
    return name


def _hash(bar) -> str:
    payload = json.dumps(
        [bar.ts.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def ingest(
    adapter: SourceAdapter,
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    interval: str = "1d",
    dsn: str = DSN,
) -> IngestReport:
    inst = BY_SYMBOL[symbol]
    rep = IngestReport(symbol=symbol, source_name="")

    try:
        rep.source_name = verify_name(adapter, inst)      # ← before writing anything
        bars = adapter.fetch(inst.source_ticker, start, end, interval)
    except (SourceError, VerificationError) as exc:
        rep.error = str(exc)
        return rep

    rep.bars_fetched = len(bars)
    if not bars:
        return rep

    request_id = uuid.uuid4().hex
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO core.instrument
                     (symbol, source, source_ticker, display_name_verified,
                      asset_class, unit, currency, verified_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s, now())
                   ON CONFLICT (symbol) DO UPDATE
                     SET display_name_verified = EXCLUDED.display_name_verified,
                         verified_at = now()""",
                (inst.symbol, inst.source, inst.source_ticker, rep.source_name,
                 inst.asset_class, inst.unit, inst.currency),
            )

            rows = [
                (inst.source, inst.symbol, interval, b.ts,
                 b.open, b.high, b.low, b.close, b.volume, _hash(b), request_id)
                for b in bars
            ]
            cur.executemany(
                """INSERT INTO raw.ohlcv_ingest
                     (source, symbol, interval, ts, open, high, low, close, volume,
                      payload_hash, request_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (source, symbol, interval, ts) DO NOTHING""",
                rows,
            )
            inserted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

            # core.bar is REBUILT from raw, not written in parallel. If the normalisation
            # turns out to be wrong, it is corrected and rebuilt without asking the source
            # for anything again — a source that may well have changed.
            cur.execute(
                """INSERT INTO core.bar
                     (symbol, interval, ts, open, high, low, close, volume, is_gap)
                   SELECT symbol, interval, ts, open, high, low, close, volume,
                          (close IS NULL)
                     FROM raw.ohlcv_ingest
                    WHERE symbol = %s AND interval = %s
                   ON CONFLICT (symbol, interval, ts) DO UPDATE
                     SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                         close=EXCLUDED.close, volume=EXCLUDED.volume,
                         is_gap=EXCLUDED.is_gap""",
                (inst.symbol, interval),
            )

            cur.execute(
                """SELECT count(*), min(ts), max(ts),
                          count(*) FILTER (WHERE is_gap)
                     FROM core.bar WHERE symbol=%s AND interval=%s""",
                (inst.symbol, interval),
            )
            total, first, last, gaps = cur.fetchone()
        conn.commit()

    rep.rows_inserted = inserted
    rep.rows_skipped = len(bars) - inserted
    rep.first_ts, rep.last_ts, rep.gaps = first, last, gaps
    return rep


def backfill(adapter: SourceAdapter, symbols, years: int = 10, **kw) -> list[IngestReport]:
    end = datetime.now(timezone.utc)
    start = end.replace(year=end.year - years)
    return [ingest(adapter, s, start, end, **kw) for s in symbols]
