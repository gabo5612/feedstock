"""Senal de compra para abastecimiento — y su verificacion.

**Lo que esta senal NO hace: predecir el precio.** No dice "el cobre va a bajar". Dice
donde esta el precio HOY respecto de su propia historia, y —esto es lo que la hace
util— **que paso historicamente cuando estuvo ahi**, medido sobre los 10 anos que hay
en la base.

La diferencia no es semantica. Un pronostico se evalua por su error; esta senal se evalua
preguntando: *"cuando dijo BARATO, comprar ahi salio mejor que comprar en un dia
cualquiera?"* Esa pregunta se responde con datos pasados y sin ningun modelo, y la
respuesta puede perfectamente ser **no** — en cuyo caso la senal se reporta igual, con su
numero, y quien la lea sabra cuanto vale.

El baseline contra el que se mide es "comprar sin mirar nada". Es el equivalente al
baseline naive del pronostico, y por la misma razon: sin el, cualquier numero que publique
la senal no significa nada.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")

# Cortes sobre `pos_rango_252d`: donde esta el cierre dentro del rango de 52 semanas.
# Elegidos como quintiles —no ajustados para que el resultado quede lindo—, y esa decision
# se toma ANTES de mirar el backtest. Moverlos despues de ver los numeros seria ajustar la
# senal a los datos con los que se la evalua.
CORTES = (
    ("muy_barato", 0.00, 0.20),
    ("barato",     0.20, 0.40),
    ("normal",     0.40, 0.60),
    ("caro",       0.60, 0.80),
    ("muy_caro",   0.80, 1.01),
)

ETIQUETAS = {
    "muy_barato": "Muy barato para su propia historia",
    "barato":     "Barato para su propia historia",
    "normal":     "En su rango habitual",
    "caro":       "Caro para su propia historia",
    "muy_caro":   "Muy caro para su propia historia",
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
    """Donde esta el precio hoy. Es una descripcion, no una prediccion."""

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
        return ETIQUETAS.get(self.banda or "", "Sin historia suficiente")


@dataclass
class Evidencia:
    """Que paso DESPUES, historicamente, cuando la senal estuvo en esta banda.

    `cambio_medio_pct` es el cambio medio del precio en los `horizonte` dias habiles
    siguientes a un dia en esta banda. `baseline_pct` es el mismo numero calculado sobre
    TODOS los dias, sin mirar la senal: comprar sin criterio.

    `ventaja_pct` = baseline − banda. Positivo significa que, historicamente, comprar en
    esta banda salio mas barato que comprar en un dia cualquiera. **Negativo significa que
    salio peor, y se publica igual.**
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
    """El paquete completo: donde esta, que paso historicamente, y cuanto confiar."""
    e = estado(symbol, dsn=dsn)
    if e is None or e.banda is None:
        return {"symbol": symbol, "estado": None,
                "aviso": "Sin 252 dias de historia: no hay con que comparar."}

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
            # El texto se arma del numero medido; no hay frases fijas de "compra fuerte".
            "lectura": (
                f"Cuando este instrumento estuvo en la banda «{e.banda}», el precio "
                f"{ev.horizonte} dias habiles despues cambio en promedio "
                f"{ev.cambio_medio_pct:+.1f}%, contra {ev.baseline_pct:+.1f}% comprando "
                f"en un dia cualquiera. Ventaja historica: {ev.ventaja_pct:+.1f} puntos "
                f"sobre {ev.n} casos."
            ),
        }
    salida["advertencia"] = (
        "Esto describe donde esta el precio respecto de su historia y que paso despues en "
        "el pasado. NO es un pronostico. Una ventaja historica chica o negativa significa "
        "que la senal no sirve para ese instrumento, y se publica igual."
    )
    return salida
