"""Data-leakage guard.

The idea is simple: **recompute every feature with the series truncated at `origin_ts` and
require the same value as with the full series.** If a feature looks ahead, truncation takes
that future away and the value changes. The test fails.

It is deliberately independent of the SQL in `features.py`: it reimplements the windows in
Python. If the guard shared code with what it audits, an error in a window definition would
slip into both and the test would pass happily. A verifier that shares the verified system's
assumption verifies nothing.
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
    con_futuro: float      # value as persisted (may contain the future)
    sin_futuro: float      # value recomputed with the series truncated

    @property
    def delta(self) -> float:
        return abs(self.con_futuro - self.sin_futuro)


def _sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _sd(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _recompute(closes: list[float]) -> dict[str, float | None]:
    """The same features, computed ONLY from what existed up to the last element."""
    if not closes:
        return {}
    today = closes[-1]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    out: dict[str, float | None] = {}

    for n in (20, 60, 252):
        sma = _sma(closes, n)
        out[f"sma_{n}d"] = sma
        out[f"dist_sma_{n}d"] = (today / sma - 1) if sma else None

    for n in (20, 60):
        v = _sd(rets[-n:]) if len(rets) >= n else None
        out[f"vol_{n}d"] = v * math.sqrt(252) if v is not None else None

    if len(closes) >= 252:
        window = closes[-252:]
        lo, hi = min(window), max(window)
        out["pos_rango_252d"] = (today - lo) / (hi - lo) if hi > lo else None
        sd, mean_ = _sd(window), sum(window) / len(window)
        out["z_252d"] = (today - mean_) / sd if sd else None
    return out


def check(
    symbol: str,
    *,
    muestras: int = 25,
    dsn: str = DSN,
    inyectar_fuga: bool = False,
) -> list[Leak]:
    """Compares what was persisted against the truncated recomputation at several
    `origin_ts` points.

    `inyectar_fuga=True` deliberately computes a **centred** moving average (one that uses
    later days). It exists to prove the guard works: a guard that never finds anything is
    indistinguishable from a broken guard.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT ts, close FROM core.bar
                WHERE symbol=%s AND interval='1d' AND close > 0 ORDER BY ts""",
            (symbol,),
        )
        series = cur.fetchall()
        cur.execute(
            """SELECT ts, name, value FROM feat.feature
                WHERE symbol=%s AND feature_version='v1'""",
            (symbol,),
        )
        persisted: dict = {}
        for ts, name, value in cur.fetchall():
            persisted.setdefault(ts, {})[name] = float(value)

    if len(series) < 300:
        return []

    findings: list[Leak] = []
    step = max(1, (len(series) - 260) // muestras)
    for i in range(260, len(series), step):
        ts = series[i][0]
        closes = [float(c) for _, c in series[: i + 1]]

        if inyectar_fuga:
            # THE LEAK: a centred mean, using 10 days AFTER `ts`.
            future = [float(c) for _, c in series[i + 1 : i + 11]]
            window = closes[-10:] + future
            expected = {"sma_20d": sum(window) / len(window)}
        else:
            expected = _recompute(closes)

        actual = persisted.get(ts, {})
        for name, value in expected.items():
            if value is None or name not in actual:
                continue
            if abs(actual[name] - value) > max(TOL, abs(value) * 1e-6):
                findings.append(
                    Leak(symbol, str(ts.date()), name, actual[name], value)
                )
    return findings
