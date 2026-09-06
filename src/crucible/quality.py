"""Data-quality monitor. The sibling of `assay` for price series.

The infrastructure to detect problems already existed — `is_gap`, `display_name_verified`,
`ingested_at` — but **nobody was looking at it**. Bad data nobody looks at is worse than
missing data: the missing kind gets noticed, the bad kind gets used.

Four checks, each against a concrete, observed failure mode:

1. **Freshness** — did the source stop updating? An instrument frozen three weeks ago still
   returns a price: the last one. Nothing warns you.
2. **Gaps** — business days with no candle. A known gap can be handled; a silent one gets
   interpolated by accident and ends up as an invented feature.
3. **Name drift** — the ticker is unchanged but the source now returns something else. It is
   the `ZN=F` failure mode, appearing AFTER the initial ingestion.
4. **Outliers** — a move of more than N sigmas in a day. It can be a source error (a shifted
   decimal) **or a real crisis**, and the monitor CANNOT tell them apart: it only flags them
   for a person to look at.

   That distinction is not theoretical. The first version of this file claimed such a jump
   "is usually a source error". On reviewing what it found, the 5 flagged on crude oil turned
   out to be **March and April 2020** — the COVID collapse, including the day of negative
   prices. Real events. The wording was corrected: a monitor that labels history as a bug is
   worse than no monitor, because it invites "cleaning" good data.

   They are never auto-corrected: touching the raw layer automatically destroys traceability.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")

DIAS_FRESCURA = 5       # business days without update before alerting
SIGMAS_SALTO = 8.0      # threshold to mark, not to judge


@dataclass
class Hallazgo:
    symbol: str
    tipo: str
    severidad: str      # "critical" · "warning" · "ok"
    detalle: str
    valor: float | None = None


def revisar(*, dsn: str = DSN) -> dict:
    hallazgos: list[Hallazgo] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT i.symbol, i.display_name_verified, i.verified_at,
                   max(b.ts)::date, count(b.*),
                   count(*) FILTER (WHERE b.is_gap)
              FROM core.instrument i LEFT JOIN core.bar b ON b.symbol = i.symbol
             GROUP BY 1,2,3 ORDER BY 1""")
        filas = cur.fetchall()

        for sym, nombre, verificado, ultimo, n, huecos in filas:
            if not n:
                hallazgos.append(Hallazgo(sym, "sin_datos", "critical",
                                          "the instrument has no candlesticks"))
                continue

            # 1) freshness
            cur.execute(
                """SELECT (CURRENT_DATE - max(ts)::date) FROM core.bar WHERE symbol=%s""",
                (sym,))
            atraso = cur.fetchone()[0] or 0
            if atraso > DIAS_FRESCURA * 2:
                hallazgos.append(Hallazgo(sym, "desactualizado", "critical",
                    f"last data {atraso} days ago ({ultimo}). The source stopped reporting.",
                    float(atraso)))
            elif atraso > DIAS_FRESCURA:
                hallazgos.append(Hallazgo(sym, "desactualizado", "warning",
                    f"last data {atraso} days ago ({ultimo})", float(atraso)))

            # 2) marked gaps
            if huecos:
                hallazgos.append(Hallazgo(sym, "huecos", "warning",
                    f"{huecos} candlestick(s) without close marked as gap", float(huecos)))

            # 3) unverified name
            if not verificado or not nombre:
                hallazgos.append(Hallazgo(sym, "sin_verificar", "critical",
                    "the source's name was never verified against the expected"))

            # 4) impossible jumps
            cur.execute("""
                WITH r AS (
                  SELECT ts, ln(close / lag(close) OVER (ORDER BY ts)) AS ret
                    FROM core.bar WHERE symbol=%s AND interval='1d' AND close > 0
                ), s AS (SELECT stddev_samp(ret) AS sd, avg(ret) AS m FROM r WHERE ret IS NOT NULL)
                SELECT count(*), max(abs(r.ret - s.m) / nullif(s.sd,0)),
                       min(r.ts)::date, max(r.ts)::date
                  FROM r, s WHERE r.ret IS NOT NULL
                   AND abs(r.ret - s.m) / nullif(s.sd,0) > %s""", (sym, SIGMAS_SALTO))
            cuenta, peor, desde, hasta = cur.fetchone()
            if cuenta:
                rango = f"{desde}" if desde == hasta else f"{desde} to {hasta}"
                hallazgos.append(Hallazgo(sym, "valor_atipico", "warning",
                    f"{cuenta} day(s) over {SIGMAS_SALTO:g}σ (worst {peor:.1f}σ, {rango}). "
                    f"May be a source error or a real crisis: the monitor cannot distinguish. Review before deciding.", float(peor)))

    criticos = sum(1 for h in hallazgos if h.severidad == "critical")
    avisos = sum(1 for h in hallazgos if h.severidad == "warning")
    return {
        "instruments": len(filas),
        "critical": criticos,
        "warning": avisos,
        "ok": criticos == 0 and avisos == 0,
        "checks": ["frescura", "huecos", "deriva de nombre", "saltos imposibles"],
        "findings": [
            {"symbol": h.symbol, "tipo": h.tipo, "severidad": h.severidad,
             "detalle": h.detalle, "valor": h.valor}
            for h in sorted(hallazgos, key=lambda x: (x.severidad != "critical", x.symbol))
        ],
    }
