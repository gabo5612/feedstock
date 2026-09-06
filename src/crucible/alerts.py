"""Alertas sobre umbrales. Corren locales, sin servicio externo.

Dos decisiones que hacen que un sistema de alertas se siga leyendo a los seis meses:

**1. Se registra la TRANSICION, no la evaluacion.** Una tabla que anota "sigue disparada"
todos los dias se vuelve ilegible en una semana y la gente deja de mirarla. Solo se escribe
cuando una regla pasa de tranquila a disparada o al reves.

**2. Una regla que no se puede evaluar NO es una regla que no dispara.** Si falta el dato,
el estado es `sin_datos`, no `ok`. Un panel que pinta en verde lo que no pudo medir es
peor que no tener panel: da confianza donde no hay informacion.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")

TIPOS = {
    "price_above":  ("precio por encima de",        "close"),
    "price_below":  ("precio por debajo de",        "close"),
    "z_above":      ("z-score por encima de",       "z_252d"),
    "z_below":      ("z-score por debajo de",       "z_252d"),
    "pos_above":    ("posicion en el rango sobre",  "pos_rango_252d"),
    "pos_below":    ("posicion en el rango bajo",   "pos_rango_252d"),
    "vol_above":    ("volatilidad anual sobre",     "vol_20d"),
}


@dataclass
class Evaluacion:
    rule_id: int
    name: str
    symbol: str | None
    kind: str
    threshold: float
    value: float | None
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

            etiqueta = TIPOS.get(kind, ("cambio de la canasta sobre", ""))[0]
            objeto = symbol or f"canasta «{basket}»"
            mensaje = (
                f"{objeto}: {etiqueta} {thr:g}" +
                (f" — actualmente {valor:.4g}" if valor is not None
                 else " — sin dato para evaluar")
            )
            salida.append(Evaluacion(rid, name, symbol or basket, kind, float(thr),
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
