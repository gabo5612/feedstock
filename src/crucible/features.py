"""Features. Todas causales, y hay un test que lo prueba.

**La regla que gobierna este archivo entero:** una feature en `ts` solo puede usar datos
con timestamp <= `ts`. Ni uno posterior, ni siquiera el propio cierre de `ts` cuando la
feature pretende estar disponible *antes* del cierre.

El look-ahead bias es lo que hace que el 95% de los proyectos de prediccion de precios
sean basura con graficos preciosos: se calcula una media movil centrada, o se normaliza
con la media de toda la serie, y el modelo "predice" usando informacion que en ese momento
no existia. El resultado se ve espectacular y no se puede reproducir en vivo ni una vez.

Acá todas las ventanas son hacia atras (`rows BETWEEN n PRECEDING AND CURRENT ROW`) y el
guard de `tests/test_leak.py` lo verifica de forma independiente: recalcula cada feature
truncando la serie en cada `origin_ts` y exige el mismo valor. Si alguna mira adelante, el
truncado da distinto y el test falla.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")

# Cambia cuando cambia la DEFINICION de una feature, no cuando se agregan filas. Dos
# predicciones solo son comparables si comparten esta version: sin ella, un cambio de
# definicion convierte una comparacion en una coincidencia.
FEATURE_VERSION = "v1"

# Ventanas en dias habiles de mercado.
VENTANAS = (20, 60, 252)


@dataclass
class FeatureReport:
    symbol: str
    rows: int
    names: tuple[str, ...]


# Todas las ventanas son `n PRECEDING AND CURRENT ROW`: hacia atras e incluyendo hoy.
# Una ventana centrada (`n PRECEDING AND n FOLLOWING`) seria fuga pura.
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
         -- Rango percentil dentro de la propia historia reciente: 0 = el mas barato de
         -- los ultimos 252 dias habiles, 1 = el mas caro. Es la base de la senal de
         -- compra, y es una DESCRIPCION del presente, no un pronostico.
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


def _derivadas(fila: dict) -> dict[str, float | None]:
    """Features derivadas de las agregadas. Aritmetica sobre la misma fila: no puede fugar."""
    close = fila["close"]
    out: dict[str, float | None] = {
        "ret_1d": fila["ret"],
        "vol_20d": fila["vol_20"],
        "vol_60d": fila["vol_60"],
    }
    for n in (20, 60, 252):
        sma = fila.get(f"sma_{n}")
        out[f"sma_{n}d"] = sma
        # Distancia relativa a su media: cuanto por encima o por debajo esta hoy.
        out[f"dist_sma_{n}d"] = (close / sma - 1) if sma else None

    lo, hi = fila["min_252"], fila["max_252"]
    # Posicion en el rango de 52 semanas. 0 = minimo del ano, 1 = maximo.
    out["pos_rango_252d"] = ((close - lo) / (hi - lo)) if (lo is not None and hi and hi > lo) else None

    sd, media = fila["sd_252"], fila["sma_252"]
    # Z-score contra su propia historia anual.
    out["z_252d"] = ((close - media) / sd) if (sd and media is not None) else None
    return out


def compute(symbol: str, *, dsn: str = DSN, persist: bool = True) -> FeatureReport:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_FEATURES, {"symbol": symbol})
            cols = [d.name for d in cur.description]
            filas = [dict(zip(cols, r)) for r in cur.fetchall()]

            registros = []
            for f in filas:
                for nombre, valor in _derivadas(f).items():
                    if valor is not None:
                        registros.append((symbol, f["ts"], nombre, float(valor), FEATURE_VERSION))

            if persist and registros:
                cur.executemany(
                    """INSERT INTO feat.feature (symbol, ts, name, value, feature_version)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (symbol, ts, name, feature_version)
                       DO UPDATE SET value = EXCLUDED.value""",
                    registros,
                )
        conn.commit()

    nombres = tuple(sorted({r[2] for r in registros}))
    return FeatureReport(symbol=symbol, rows=len(registros), names=nombres)


def compute_all(symbols, **kw) -> list[FeatureReport]:
    return [compute(s, **kw) for s in symbols]
