"""Alerts on thresholds. Run locally, no external service.

Two decisions that make an alert system continue reading every six months:

**1. Log the TRANSITION, not the evaluation.** A table that notes "still firing"
every day becomes unreadable in a week and people stop looking at it. Only write
when a rule goes from calm to fired or vice versa.

**2. A rule that can't be evaluated IS NOT a rule that doesn't fire.** If data is missing,
the state is `sin_datos`, not `ok`. A panel that paints green what couldn't measure is
worse than no panel: it gives confidence where there's no information.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("FEEDSTOCK_DSN", "postgresql://feedstock:feedstock@localhost:5434/feedstock")

TIPOS = {
    "price_above":  ("price above",        "close"),
    "price_below":  ("price below",        "close"),
    "z_above":      ("z-score above",       "z_252d"),
    "z_below":      ("z-score below",       "z_252d"),
    "pos_above":    ("position in range above",  "pos_rango_252d"),
    "pos_below":    ("position in range below",   "pos_rango_252d"),
    "vol_above":    ("annual volatility above",     "vol_20d"),
}


@dataclass
class Evaluation:
    rule_id: int
    name: str
    symbol: str | None
    kind: str
    threshold: float
    value: float | None
    # These three values are data, not prose: they are stored, compared and
    # rendered by the dashboard. Renaming them would break stored history.
    estado: str            # "disparada" · "ok" · "sin_datos"
    mensaje: str


def crear_regla(name: str, kind: str, threshold: float, *, symbol: str | None = None,
                basket: str | None = None, dsn: str = DSN) -> int:
    if kind not in TIPOS and kind != "basket_change_pct":
        raise ValueError(f"tipo desconocido: {kind}. Validos: {sorted(TIPOS) + ['basket_change_pct']}")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO core.alert_rule (name, symbol, basket, kind, threshold)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (name, symbol, basket, kind, threshold))
        rid = cur.fetchone()[0]
        conn.commit()
    return rid


def _valor_actual(cur, symbol: str, campo: str) -> float | None:
    if campo == "close":
        cur.execute(
            """SELECT close FROM core.bar WHERE symbol=%s AND interval='1d'
                AND close IS NOT NULL ORDER BY ts DESC LIMIT 1""", (symbol,))
    else:
        cur.execute(
            """SELECT value FROM feat.feature
                WHERE symbol=%s AND name=%s AND feature_version='v1'
                ORDER BY ts DESC LIMIT 1""", (symbol, campo))
    fila = cur.fetchone()
    return float(fila[0]) if fila and fila[0] is not None else None


def evaluar(*, dsn: str = DSN, registrar: bool = True) -> list[Evaluacion]:
    salida: list[Evaluacion] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, name, symbol, basket, kind, threshold FROM core.alert_rule
                WHERE enabled ORDER BY id""")
        reglas = cur.fetchall()

        for rid, name, symbol, basket, kind, thr in reglas:
            valor, estado = None, "sin_datos"

            if kind == "basket_change_pct" and basket:
                from .basket import serie_costo
                d = serie_costo(basket, days=40, dsn=dsn)
                if len(d["series"]) >= 2:
                    valor = (d["series"][-1][1] / d["series"][0][1] - 1) * 100
                    estado = "disparada" if valor >= thr else "ok"
            elif symbol and kind in TIPOS:
                _, campo = TIPOS[kind]
                valor = _valor_actual(cur, symbol, campo)
                if valor is not None:
                    arriba = kind.endswith("_above")
                    estado = "disparada" if (valor >= thr if arriba else valor <= thr) else "ok"

            etiqueta = TIPOS.get(kind, ("change in basket over", ""))[0]
            objeto = symbol or f"basket «{basket}»"
            mensaje = (
                f"{objeto}: {etiqueta} {thr:g}" +
                (f" — currently {valor:.4g}" if valor is not None
                 else " — no data to evaluate")
            )
            salida.append(Evaluation(rid, name, symbol or basket, kind, float(thr),
                                     valor, estado, mensaje))

            if registrar and estado != "sin_datos":
                # Solo se anota la TRANSICION.
                cur.execute(
                    """SELECT firing FROM core.alert_event WHERE rule_id=%s
                        ORDER BY ts DESC LIMIT 1""", (rid,))
                previo = cur.fetchone()
                ahora = estado == "disparada"
                if previo is None or previo[0] != ahora:
                    cur.execute(
                        """INSERT INTO core.alert_event (rule_id, firing, value, mensaje)
                           VALUES (%s,%s,%s,%s)""", (rid, ahora, valor, mensaje))
        conn.commit()
    return salida


def historial(*, limite: int = 40, dsn: str = DSN) -> list[dict]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT e.ts, r.name, e.firing, e.value, e.mensaje
                 FROM core.alert_event e JOIN core.alert_rule r ON r.id = e.rule_id
                ORDER BY e.ts DESC LIMIT %s""", (limite,))
        return [{"ts": str(t), "rule": n, "firing": f, "value": v, "mensaje": m}
                for t, n, f, v, m in cur.fetchall()]


def listar(*, dsn: str = DSN) -> list[dict]:
    ev = evaluar(dsn=dsn, registrar=False)
    return [{"id": e.rule_id, "name": e.name, "target": e.symbol, "kind": e.kind,
             "threshold": e.threshold, "value": e.value, "estado": e.estado,
             "mensaje": e.mensaje} for e in ev]
