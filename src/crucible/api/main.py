"""Dashboard API. Serves the page and the data, all from the local machine.

There is no external service and no telemetry: the page is served by the same process that
reads the database. It is the same criterion as the rest of the project — the data does not
leave the machine — and it is also what lets this work in a plant with no internet.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")
WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="crucible", docs_url="/api/docs")


def _conn() -> psycopg.Connection:
    return psycopg.connect(DSN, connect_timeout=5)


@app.get("/api/health")
def health() -> JSONResponse:
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM core.bar")
            barras = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM core.instrument")
            n = cur.fetchone()[0]
        return JSONResponse({"ok": True, "instruments": n, "bars": barras})
    except psycopg.OperationalError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)


@app.get("/api/instruments")
def instruments() -> list[dict]:
    """Every instrument with its latest price and change. Feeds the sidebar list."""
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            WITH ult AS (
              SELECT DISTINCT ON (symbol) symbol, ts, close
                FROM core.bar WHERE interval='1d' AND close IS NOT NULL
               ORDER BY symbol, ts DESC
            ),
            prev AS (
              SELECT b.symbol, b.close
                FROM core.bar b
                JOIN ult u ON u.symbol = b.symbol
               WHERE b.interval='1d' AND b.close IS NOT NULL
                 AND b.ts < u.ts - interval '29 days'
               ORDER BY b.symbol, b.ts DESC
            )
            SELECT i.symbol, i.display_name_verified, i.asset_class, i.unit, i.currency,
                   u.close, u.ts::date,
                   (SELECT close FROM prev p WHERE p.symbol=i.symbol LIMIT 1),
                   (SELECT count(*) FROM core.bar b WHERE b.symbol=i.symbol),
                   (SELECT min(ts)::date FROM core.bar b WHERE b.symbol=i.symbol)
              FROM core.instrument i
              LEFT JOIN ult u ON u.symbol = i.symbol
             ORDER BY i.asset_class, i.symbol""")
        rows = cur.fetchall()

    out = []
    for sym, name, asset_class, unit, currency, last, date_, month_ago, n, since in rows:
        change = None
        if last is not None and month_ago:
            change = (last - month_ago) / month_ago * 100
        out.append({
            "symbol": sym, "name": name, "asset_class": asset_class,
            "unit": unit, "currency": currency,
            "last": last, "last_date": str(date_) if date_ else None,
            "change_30d_pct": change, "bars": n,
            "since": str(since) if since else None,
        })
    return out


@app.get("/api/series")
def series(
    symbols: str = Query(..., description="lista separada por comas"),
    days: int = Query(365, ge=5, le=4000),
) -> dict:
    """Close series for the requested symbols.

    Returns RAW values. Indexing to base 100 happens in the client, and that decision is
    deliberate: whoever looks at the JSON sees prices, not a transformation they would have
    to infer.
    """
    requested = [s.strip() for s in symbols.split(",") if s.strip()]
    if not requested:
        raise HTTPException(400, "no symbols given")
    if len(requested) > 8:
        # Eight is the ceiling of the validated categorical palette. A ninth colour is not
        # invented: the selection is trimmed.
        raise HTTPException(400, "at most 8 series at a time")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT symbol, ts::date, close
              FROM core.bar
             WHERE symbol = ANY(%s) AND interval='1d' AND ts >= %s AND close IS NOT NULL
             ORDER BY symbol, ts""",
            (requested, since))
        rows = cur.fetchall()

    by_symbol: dict[str, list] = {s: [] for s in requested}
    for sym, f, close in rows:
        by_symbol[sym].append([str(f), float(close)])
    return {"days": days, "series": by_symbol}


@app.get("/api/stats")
def stats(symbol: str, days: int = Query(365, ge=5, le=4000)) -> dict:
    """Statistics for one instrument over the requested window."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT count(*), min(low), max(high), min(ts)::date, max(ts)::date,
                   stddev_samp(close), avg(close)
              FROM core.bar
             WHERE symbol=%s AND interval='1d' AND ts >= %s AND close IS NOT NULL""",
            (symbol, since))
        n, low, high, first, last, stdev, mean_ = cur.fetchone()

        # Annualised volatility over daily log returns. 252 = market business days in a
        # year, the standard convention.
        cur.execute("""
            WITH r AS (
              SELECT ln(close / lag(close) OVER (ORDER BY ts)) AS ret
                FROM core.bar
               WHERE symbol=%s AND interval='1d' AND ts >= %s AND close > 0
            )
            SELECT stddev_samp(ret) * sqrt(252) * 100 FROM r WHERE ret IS NOT NULL""",
            (symbol, since))
        vol = cur.fetchone()[0]

    if not n:
        raise HTTPException(404, f"no data for {symbol}")
    return {
        "symbol": symbol, "bars": n,
        "min": low, "max": high, "avg": mean_,
        "from": str(first), "to": str(last),
        "annualized_vol_pct": vol,
    }


@app.get("/api/correlation")
def correlation(symbols: str, days: int = Query(365, ge=30, le=4000)) -> dict:
    """Correlation of daily returns between instruments.

    This is the question a plant actually cares about: **what moves together**. If copper and
    energy are correlated, hedging one does not hedge the other.

    Over RETURNS, not prices: two trending series correlate highly even when unrelated — the
    classic trap of this calculation.
    """
    requested = [s.strip() for s in symbols.split(",") if s.strip()]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            WITH r AS (
              SELECT symbol, ts,
                     ln(close / lag(close) OVER (PARTITION BY symbol ORDER BY ts)) AS ret
                FROM core.bar
               WHERE symbol = ANY(%s) AND interval='1d' AND ts >= %s AND close > 0
            )
            SELECT a.symbol, b.symbol, corr(a.ret, b.ret), count(*)
              FROM r a JOIN r b ON a.ts = b.ts
             WHERE a.ret IS NOT NULL AND b.ret IS NOT NULL
             GROUP BY 1,2""",
            (requested, since))
        rows = cur.fetchall()
    return {
        "symbols": requested,
        "matrix": [{"a": a, "b": b, "r": r, "n": n} for a, b, r, n in rows],
    }


@app.get("/api/signal")
def signal(symbol: str, horizon: int = Query(60, ge=5, le=252)) -> dict:
    """Where the price sits relative to its history, and what happened afterwards."""
    from ..signals import recomendacion

    return recomendacion(symbol, horizonte=horizon)


@app.get("/api/signals")
def signals(horizon: int = Query(60, ge=5, le=252)) -> list[dict]:
    from ..instruments import INSTRUMENTS
    from ..signals import recomendacion

    return [recomendacion(i.symbol, horizonte=horizon) for i in INSTRUMENTS]


@app.get("/api/baskets")
def baskets() -> list[dict]:
    from ..basket import listar

    return listar()


@app.get("/api/basket")
def basket_cost(name: str, days: int = Query(365, ge=30, le=4000)) -> dict:
    from ..basket import serie_costo

    return serie_costo(name, days=days)


@app.post("/api/basket/scenario")
def basket_scenario(payload: dict) -> dict:
    """`{"name": "...", "shocks": {"copper": 10, "natgas": -20}}`"""
    from ..basket import escenario

    nombre = payload.get("name")
    if not nombre:
        raise HTTPException(400, "`name` is required")
    return escenario(nombre, payload.get("shocks") or {})


@app.get("/api/alerts")
def alerts() -> list[dict]:
    from ..alerts import listar

    return listar()


@app.get("/api/alerts/history")
def alerts_history(limit: int = Query(40, ge=1, le=200)) -> list[dict]:
    from ..alerts import historial

    return historial(limite=limit)


@app.get("/api/quality")
def quality() -> dict:
    from ..quality import revisar

    return revisar()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")
