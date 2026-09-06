"""Guard de fuga de datos.

La idea, y es simple: **recalcular cada feature con la serie truncada en `origin_ts` y
exigir el mismo valor que con la serie completa.** Si una feature mira hacia adelante, el
truncado le saca ese futuro y el valor cambia. El test falla.

Es deliberadamente independiente del SQL de `features.py`: reimplementa las ventanas en
Python. Si el guard compartiera codigo con lo que audita, un error en la definicion de
ventana se colaria en los dos y el test pasaria feliz. Un verificador que comparte la
suposicion del sistema verificado no verifica nada.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")
TOL = 1e-9


@dataclass(frozen=True)
class Leak:
    symbol: str
    origin_ts: str
    feature: str
    con_futuro: float
    sin_futuro: float

    @property
    def delta(self) -> float:
        return abs(self.con_futuro - self.sin_futuro)


def _sma(cierres: list[float], n: int) -> float | None:
    return sum(cierres[-n:]) / n if len(cierres) >= n else None


def _sd(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _recalcular(cierres: list[float]) -> dict[str, float | None]:
    """Las mismas features, calculadas SOLO con lo que habia hasta el ultimo elemento."""
    if not cierres:
        return {}
    hoy = cierres[-1]
    rets = [math.log(cierres[i] / cierres[i - 1]) for i in range(1, len(cierres))]
    out: dict[str, float | None] = {}

    for n in (20, 60, 252):
        sma = _sma(cierres, n)
        out[f"sma_{n}d"] = sma
        out[f"dist_sma_{n}d"] = (hoy / sma - 1) if sma else None

    for n in (20, 60):
        v = _sd(rets[-n:]) if len(rets) >= n else None
        out[f"vol_{n}d"] = v * math.sqrt(252) if v is not None else None

    if len(cierres) >= 252:
        ventana = cierres[-252:]
        lo, hi = min(ventana), max(ventana)
        out["pos_rango_252d"] = (hoy - lo) / (hi - lo) if hi > lo else None
        sd, media = _sd(ventana), sum(ventana) / len(ventana)
        out["z_252d"] = (hoy - media) / sd if sd else None
    return out


def check(
    symbol: str,
    *,
    muestras: int = 25,
    dsn: str = DSN,
    inyectar_fuga: bool = False,
) -> list[Leak]:
    """Compara lo persistido contra el recalculo truncado en varios `origin_ts`.

    `inyectar_fuga=True` calcula a proposito una media movil **centrada** (que usa dias
    posteriores). Sirve para probar que el guard sirve: un guard que nunca encuentra nada
    es indistinguible de un guard roto.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT ts, close FROM core.bar
                WHERE symbol=%s AND interval='1d' AND close > 0 ORDER BY ts""",
            (symbol,),
        )
        serie = cur.fetchall()
        cur.execute(
            """SELECT ts, name, value FROM feat.feature
                WHERE symbol=%s AND feature_version='v1'""",
            (symbol,),
        )
        persistido: dict = {}
        for ts, name, value in cur.fetchall():
            persistido.setdefault(ts, {})[name] = float(value)

    if len(serie) < 300:
        return []

    hallazgos: list[Leak] = []
    paso = max(1, (len(serie) - 260) // muestras)
    for i in range(260, len(serie), paso):
        ts = serie[i][0]
        cierres = [float(c) for _, c in serie[: i + 1]]

        if inyectar_fuga:
            # LA FUGA: media centrada, usa 10 dias POSTERIORES a `ts`.
            futuro = [float(c) for _, c in serie[i + 1 : i + 11]]
            ventana = cierres[-10:] + futuro
            esperado = {"sma_20d": sum(ventana) / len(ventana)}
        else:
            esperado = _recalcular(cierres)

        real = persistido.get(ts, {})
        for nombre, valor in esperado.items():
            if valor is None or nombre not in real:
                continue
            if abs(real[nombre] - valor) > max(TOL, abs(valor) * 1e-6):
                hallazgos.append(
                    Leak(symbol, str(ts.date()), nombre, real[nombre], valor)
                )
    return hallazgos
