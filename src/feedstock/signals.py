"""Procurement buy signal — and its verification.

**What this signal does NOT do: predict the price.** It does not say "copper is going to
fall". It says where the price sits TODAY relative to its own history and — this is what
makes it useful — **what happened historically when it sat there**, measured over the 10
years in the database.

The difference is not semantic. A forecast is evaluated by its error; this signal is
evaluated by asking: *"when it said CHEAP, did buying there work out better than buying on
any random day?"* That question is answered with past data and no model at all, and the
answer can perfectly well be **no** — in which case the signal is reported anyway, with its
number, and whoever reads it knows what it is worth.

The baseline it is measured against is "buying without looking at anything". It is the
equivalent of the forecast's naive baseline, and for the same reason: without it, any number
the signal publishes means nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("FEEDSTOCK_DSN", "postgresql://feedstock:feedstock@localhost:5434/feedstock")

# Cut points over `pos_rango_252d`: where the close sits within the 52-week range.
# Chosen as quintiles — not tuned to make the result look good — and that decision is taken
# BEFORE looking at the backtest. Moving them after seeing the numbers would be fitting the
# signal to the very data it is evaluated against.
CORTES = (
    ("muy_barato", 0.00, 0.20),
    ("barato",     0.20, 0.40),
    ("normal",     0.40, 0.60),
    ("caro",       0.60, 0.80),
    ("muy_caro",   0.80, 1.01),
)

# The band keys are data — they are stored, compared and rendered — so they keep their
# original names. Only the labels shown to a person are translated.
ETIQUETAS = {
    "muy_barato": "Very cheap relative to its own history",
    "barato":     "Cheap relative to its own history",
    "normal":     "Within its usual range",
    "caro":       "Expensive relative to its own history",
    "muy_caro":   "Very expensive relative to its own history",
}


def clasificar(pos: float | None) -> str | None:
    if pos is None:
        return None
    for nombre, lo, hi in CORTES:
        if lo <= pos < hi:
            return nombre
    return None


@dataclass
class Estado:
    """Where the price sits today. A description, not a prediction."""

    symbol: str
    ts: str
    close: float
    pos_rango: float | None
    z: float | None
    banda: str | None
    dist_sma_252d: float | None
    vol_20d: float | None

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS.get(self.banda or "", "Not enough history")


@dataclass
class Evidencia:
    """What happened AFTERWARDS, historically, when the signal sat in this band.

    `cambio_medio_pct` is the mean price change over the `horizonte` business days following
    a day in this band. `baseline_pct` is the same number computed over ALL days, without
    looking at the signal: buying with no criterion.

    `ventaja_pct` = baseline − band. Positive means that, historically, buying in this band
    came out cheaper than buying on any random day. **Negative means it came out worse, and
    it is published all the same.**
    """

    symbol: str
    banda: str
    horizonte: int
    n: int
    cambio_medio_pct: float
    baseline_pct: float
    veces_bajo_despues: float

    @property
    def ventaja_pct(self) -> float:
        return self.baseline_pct - self.cambio_medio_pct


SQL_ESTADO = """
WITH f AS (
  SELECT ts, name, value FROM feat.feature
   WHERE symbol=%(symbol)s AND feature_version='v1'
     AND name IN ('pos_rango_252d','z_252d','dist_sma_252d','vol_20d')
),
ult AS (SELECT max(ts) AS ts FROM f)
SELECT u.ts,
       (SELECT close FROM core.bar b WHERE b.symbol=%(symbol)s AND b.ts=u.ts),
       max(value) FILTER (WHERE name='pos_rango_252d'),
       max(value) FILTER (WHERE name='z_252d'),
       max(value) FILTER (WHERE name='dist_sma_252d'),
       max(value) FILTER (WHERE name='vol_20d')
  FROM ult u JOIN f ON f.ts = u.ts
 GROUP BY u.ts
"""


def estado(symbol: str, *, dsn: str = DSN) -> Estado | None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL_ESTADO, {"symbol": symbol})
        fila = cur.fetchone()
    if not fila or fila[1] is None:
        return None
    ts, close, pos, z, dist, vol = fila
    return Estado(
        symbol=symbol, ts=str(ts.date()), close=float(close),
        pos_rango=float(pos) if pos is not None else None,
        z=float(z) if z is not None else None,
        banda=clasificar(float(pos)) if pos is not None else None,
        dist_sma_252d=float(dist) if dist is not None else None,
        vol_20d=float(vol) if vol is not None else None,
    )


SQL_EVIDENCIA = """
WITH p AS (
  SELECT b.ts, b.close,
         f.value AS pos,
         lead(b.close, %(h)s) OVER (ORDER BY b.ts) AS futuro
    FROM core.bar b
    JOIN feat.feature f
      ON f.symbol = b.symbol AND f.ts = b.ts
     AND f.name = 'pos_rango_252d' AND f.feature_version = 'v1'
   WHERE b.symbol = %(symbol)s AND b.interval = '1d' AND b.close > 0
),
c AS (
  SELECT (futuro / close - 1) * 100 AS cambio, pos
    FROM p WHERE futuro IS NOT NULL AND pos IS NOT NULL
)
SELECT
  (SELECT avg(cambio) FROM c)                                      AS baseline,
  count(*)                                                          AS n,
  avg(cambio)                                                       AS medio,
  avg(CASE WHEN cambio < 0 THEN 1.0 ELSE 0.0 END) * 100             AS bajo_despues
  FROM c WHERE pos >= %(lo)s AND pos < %(hi)s
"""


def evidencia(symbol: str, banda: str, horizonte: int = 60, *, dsn: str = DSN) -> Evidencia | None:
    corte = next((c for c in CORTES if c[0] == banda), None)
    if corte is None:
        return None
    _, lo, hi = corte
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL_EVIDENCIA,
                    {"symbol": symbol, "h": horizonte, "lo": lo, "hi": hi})
        base, n, medio, bajo = cur.fetchone()
    if not n or medio is None:
        return None
    return Evidencia(
        symbol=symbol, banda=banda, horizonte=horizonte, n=n,
        cambio_medio_pct=float(medio), baseline_pct=float(base),
        veces_bajo_despues=float(bajo),
    )


def recomendacion(symbol: str, *, horizonte: int = 60, dsn: str = DSN) -> dict:
    """The full package: where it sits, what happened historically, and how much to trust it."""
    e = estado(symbol, dsn=dsn)
    if e is None or e.banda is None:
        return {"symbol": symbol, "estado": None,
                "aviso": "Fewer than 252 days of history: nothing to compare against."}

    ev = evidencia(symbol, e.banda, horizonte, dsn=dsn)
    salida = {
        "symbol": symbol,
        "fecha": e.ts,
        "close": e.close,
        "banda": e.banda,
        "etiqueta": e.etiqueta,
        "pos_rango_252d": e.pos_rango,
        "z_252d": e.z,
        "vol_20d": e.vol_20d,
        "horizonte_dias": horizonte,
    }
    if ev:
        salida |= {
            "n_historico": ev.n,
            "cambio_medio_pct": ev.cambio_medio_pct,
            "baseline_pct": ev.baseline_pct,
            "ventaja_pct": ev.ventaja_pct,
            "veces_bajo_despues_pct": ev.veces_bajo_despues,
            # The text is assembled from the measured number; there are no canned
            # "strong buy" phrases anywhere.
            "lectura": (
                f"When this instrument sat in the «{e.banda}» band, the price "
                f"{ev.horizonte} business days later changed on average "
                f"{ev.cambio_medio_pct:+.1f}%, against {ev.baseline_pct:+.1f}% when buying "
                f"on any random day. Historical edge: {ev.ventaja_pct:+.1f} points over "
                f"{ev.n} cases."
            ),
        }
    salida["advertencia"] = (
        "This describes where the price sits relative to its history and what happened "
        "afterwards in the past. It is NOT a forecast. A small or negative historical edge "
        "means the signal is useless for that instrument, and it is published all the same."
    )
    return salida
