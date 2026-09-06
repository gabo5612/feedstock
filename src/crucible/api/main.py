"""API del dashboard. Sirve la pagina y los datos, todo desde la maquina local.

No hay servicio externo ni telemetria: la pagina se sirve del mismo proceso que lee la
base. Es el mismo criterio que el resto del proyecto — los datos no salen de la maquina —
y ademas es lo que permite que esto funcione en una planta sin internet.
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
    """Cada instrumento con su ultimo precio y su variacion. Alimenta la lista lateral."""
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
        filas = cur.fetchall()

    salida = []
    for sym, nombre, clase, unidad, moneda, ultimo, fecha, hace30, n, desde in filas:
        cambio = None
        if ultimo is not None and hace30:
            cambio = (ultimo - hace30) / hace30 * 100
        salida.append({
            "symbol": sym, "name": nombre, "asset_class": clase,
            "unit": unidad, "currency": moneda,
            "last": ultimo, "last_date": str(fecha) if fecha else None,
            "change_30d_pct": cambio, "bars": n,
            "since": str(desde) if desde else None,
        })
    return salida


@app.get("/api/series")
def series(
    symbols: str = Query(..., description="lista separada por comas"),
    days: int = Query(365, ge=5, le=4000),
) -> dict:
    """Series de cierre para los simbolos pedidos.

    Devuelve los valores CRUDOS. La indexacion a base 100 se hace en el cliente, y esa
    decision es deliberada: quien mire el JSON ve precios, no una transformacion que
    tendria que deducir.
    """
    pedidos = [s.strip() for s in symbols.split(",") if s.strip()]
    if not pedidos:
        raise HTTPException(400, "sin simbolos")
    if len(pedidos) > 8:
        # Ocho es el tope de la paleta categorica validada. Un noveno color no se
        # inventa: se recorta la seleccion.
        raise HTTPException(400, "maximo 8 series a la vez")

    desde = datetime.now(timezone.utc) - timedelta(days=days)
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT symbol, ts::date, close
              FROM core.bar
             WHERE symbol = ANY(%s) AND interval='1d' AND ts >= %s AND close IS NOT NULL
             ORDER BY symbol, ts""",
            (pedidos, desde))
        filas = cur.fetchall()

    por_symbol: dict[str, list] = {s: [] for s in pedidos}
    for sym, f, close in filas:
        por_symbol[sym].append([str(f), float(close)])
    return {"days": days, "series": por_symbol}


@app.get("/api/stats")
def stats(symbol: str, days: int = Query(365, ge=5, le=4000)) -> dict:
    """Estadisticas de un instrumento en la ventana pedida."""
    desde = datetime.now(timezone.utc) - timedelta(days=days)
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT count(*), min(low), max(high), min(ts)::date, max(ts)::date,
                   stddev_samp(close), avg(close)
              FROM core.bar
             WHERE symbol=%s AND interval='1d' AND ts >= %s AND close IS NOT NULL""",
            (symbol, desde))
        n, minimo, maximo, ini, fin, desvio, media = cur.fetchone()

        # Volatilidad anualizada sobre retornos logaritmicos diarios. 252 = dias habiles
        # de mercado en un ano, la convencion estandar.
        cur.execute("""
            WITH r AS (
              SELECT ln(close / lag(close) OVER (ORDER BY ts)) AS ret
                FROM core.bar
               WHERE symbol=%s AND interval='1d' AND ts >= %s AND close > 0
            )
            SELECT stddev_samp(ret) * sqrt(252) * 100 FROM r WHERE ret IS NOT NULL""",
            (symbol, desde))
        vol = cur.fetchone()[0]

    if not n:
        raise HTTPException(404, f"sin datos para {symbol}")
    return {
        "symbol": symbol, "bars": n,
        "min": minimo, "max": maximo, "avg": media,
        "from": str(ini), "to": str(fin),
        "annualized_vol_pct": vol,
    }


@app.get("/api/correlation")
def correlation(symbols: str, days: int = Query(365, ge=30, le=4000)) -> dict:
    """Correlacion de retornos diarios entre instrumentos.

    Es la pregunta que de verdad le importa a una planta: **que se mueve junto**. Si el
    cobre y la energia estan correlacionados, cubrir uno no cubre el otro.

    Sobre RETORNOS, no sobre precios: dos series con tendencia dan correlacion alta
    aunque no tengan nada que ver — la trampa clasica de este calculo.
    """
    pedidos = [s.strip() for s in symbols.split(",") if s.strip()]
    desde = datetime.now(timezone.utc) - timedelta(days=days)
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
            (pedidos, desde))
        filas = cur.fetchall()
    return {
        "symbols": pedidos,
        "matrix": [{"a": a, "b": b, "r": r, "n": n} for a, b, r, n in filas],
    }


@app.get("/api/signal")
def signal(symbol: str, horizon: int = Query(60, ge=5, le=252)) -> dict:
    """Donde esta el precio respecto de su historia, y que paso despues historicamente."""
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
        raise HTTPException(400, "falta `name`")
    return escenario(nombre, payload.get("shocks") or {})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")
