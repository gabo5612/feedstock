"""Ingesta: fuente → raw.ohlcv_ingest → core.bar.

Dos propiedades que el resto del sistema da por sentadas y que se garantizan aca:

**1. La verificacion de nombre corre ANTES de escribir una sola fila.** Si el nombre que
devuelve la fuente no contiene el fragmento esperado, el instrumento se rechaza entero.
`ZN=F` devuelve "10-Year T-Note Futures" y no "Zinc": sin esta comprobacion entraria como
zinc, contaminaria el dataset de metales y no habria **ninguna** senal de que algo anda
mal. Un modelo entrenado encima daria numeros perfectamente plausibles y perfectamente
falsos.

**2. La reingesta es idempotente.** La PK de `raw.ohlcv_ingest` es
(source, symbol, interval, ts) y se inserta con ON CONFLICT DO NOTHING. Correr el backfill
dos veces sobre el mismo tramo no duplica una fila. Es lo que permite reintentar sin
pensar.
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
    """El nombre de la fuente no coincide con lo esperado. No se escribio nada."""


@dataclass
class IngestReport:
    symbol: str
    source_name: str
    bars_fetched: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0        # ya estaban: prueba de idempotencia
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    gaps: int = 0
    error: str | None = None


def verify_name(adapter: SourceAdapter, inst: Instrument) -> str:
    """Comprueba que la fuente devuelva el instrumento que creemos. Falla fuerte."""
    nombre = adapter.display_name(inst.source_ticker)
    if inst.expect_name.lower() not in nombre.lower():
        raise VerificationError(
            f"{inst.symbol}: el ticker {inst.source_ticker!r} devuelve {nombre!r}, que no "
            f"contiene {inst.expect_name!r}. NO se ingirio nada. Si el ticker cambio de "
            f"significado, corregi el registro; no relajes esta comprobacion."
        )
    return nombre


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
        rep.source_name = verify_name(adapter, inst)      # ← antes de escribir nada
        barras = adapter.fetch(inst.source_ticker, start, end, interval)
    except (SourceError, VerificationError) as exc:
        rep.error = str(exc)
        return rep

    rep.bars_fetched = len(barras)
    if not barras:
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

            filas = [
                (inst.source, inst.symbol, interval, b.ts,
                 b.open, b.high, b.low, b.close, b.volume, _hash(b), request_id)
                for b in barras
            ]
            cur.executemany(
                """INSERT INTO raw.ohlcv_ingest
                     (source, symbol, interval, ts, open, high, low, close, volume,
                      payload_hash, request_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (source, symbol, interval, ts) DO NOTHING""",
                filas,
            )
            insertadas = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

            # core.bar se RECONSTRUYE desde raw, no se escribe en paralelo. Si la
            # normalizacion resulta estar mal, se corrige y se reconstruye sin volver a
            # pedirle nada a la fuente — que ademas puede haber cambiado.
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
            total, primero, ultimo, huecos = cur.fetchone()
        conn.commit()

    rep.rows_inserted = insertadas
    rep.rows_skipped = len(barras) - insertadas
    rep.first_ts, rep.last_ts, rep.gaps = primero, ultimo, huecos
    return rep


def backfill(adapter: SourceAdapter, symbols, years: int = 10, **kw) -> list[IngestReport]:
    end = datetime.now(timezone.utc)
    start = end.replace(year=end.year - years)
    return [ingest(adapter, s, start, end, **kw) for s in symbols]
