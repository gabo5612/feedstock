"""Canasta de costo, exposicion y escenarios.

Responde la pregunta que de verdad tiene una planta: **cuanto me cuesta producir una
unidad, como evoluciono ese costo, y que insumo lo movio.** Un grafico de precios de
commodities no responde eso; una canasta si.

Tres cosas salen del mismo calculo:
  · **costo**      — la serie del costo unitario en el tiempo
  · **exposicion** — cuanto pesa cada insumo en el costo de hoy
  · **escenario**  — cuanto cambia el costo si un insumo se mueve X%
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import psycopg

from .units import convertir, unidad_de_precio

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")


@dataclass
class Componente:
    symbol: str
    nombre: str
    qty: float
    qty_unit: str
    price_unit: str
    qty_en_unidad_de_precio: float
    precio: float | None = None
    costo: float | None = None

    @property
    def peso_pct(self) -> float | None:
        return None


@dataclass
class Canasta:
    name: str
    description: str | None
    output_unit: str
    componentes: list[Componente] = field(default_factory=list)


def crear(name: str, items: list[dict], *, description: str = "",
          output_unit: str = "tonelada de producto", dsn: str = DSN) -> Canasta:
    """`items`: [{symbol, qty, qty_unit, nota?}]. Valida las unidades ANTES de guardar."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # La validacion va primero: una canasta guardada a medias con una unidad
        # imposible es peor que un error.
        for it in items:
            cur.execute("SELECT unit FROM core.instrument WHERE symbol=%s", (it["symbol"],))
            fila = cur.fetchone()
            if not fila:
                raise ValueError(f"{it['symbol']} no existe en el registro de instrumentos")
            convertir(float(it["qty"]), it["qty_unit"], unidad_de_precio(fila[0]))

        cur.execute(
            """INSERT INTO core.basket (name, description, output_unit) VALUES (%s,%s,%s)
               ON CONFLICT (name) DO UPDATE SET description=EXCLUDED.description,
                                                output_unit=EXCLUDED.output_unit""",
            (name, description, output_unit))
        cur.execute("DELETE FROM core.basket_item WHERE basket=%s", (name,))
        cur.executemany(
            """INSERT INTO core.basket_item (basket, symbol, qty, qty_unit, nota)
               VALUES (%s,%s,%s,%s,%s)""",
            [(name, i["symbol"], float(i["qty"]), i["qty_unit"], i.get("nota")) for i in items])
        conn.commit()
    return cargar(name, dsn=dsn)


def cargar(name: str, *, dsn: str = DSN) -> Canasta | None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT name, description, output_unit FROM core.basket WHERE name=%s",
                    (name,))
        cab = cur.fetchone()
        if not cab:
            return None
        cur.execute(
            """SELECT bi.symbol, i.display_name_verified, bi.qty, bi.qty_unit, i.unit
                 FROM core.basket_item bi JOIN core.instrument i ON i.symbol = bi.symbol
                WHERE bi.basket=%s ORDER BY bi.symbol""", (name,))
        comps = []
        for sym, nombre, qty, qunit, punit in cur.fetchall():
            up = unidad_de_precio(punit)
            comps.append(Componente(
                symbol=sym, nombre=nombre, qty=float(qty), qty_unit=qunit,
                price_unit=up, qty_en_unidad_de_precio=convertir(float(qty), qunit, up)))
    return Canasta(name=cab[0], description=cab[1], output_unit=cab[2], componentes=comps)


def serie_costo(name: str, *, days: int = 365, dsn: str = DSN) -> dict:
    """Costo unitario dia por dia.

    Solo se computa un dia si TODOS los insumos cotizaron ese dia. Rellenar el faltante
    con el ultimo precio conocido produciria una serie que parece continua y esconde que
    un insumo dejo de reportar — el mismo criterio que marcar los huecos en `core.bar`.
    """
    c = cargar(name, dsn=dsn)
    if not c or not c.componentes:
        return {"basket": name, "series": [], "components": []}

    syms = [x.symbol for x in c.componentes]
    factores = {x.symbol: x.qty_en_unidad_de_precio for x in c.componentes}

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT ts::date, symbol, close FROM core.bar
                WHERE symbol = ANY(%s) AND interval='1d' AND close IS NOT NULL
                  AND ts >= now() - (%s || ' days')::interval
                ORDER BY ts""", (syms, days))
        por_dia: dict = {}
        for f, sym, close in cur.fetchall():
            por_dia.setdefault(f, {})[sym] = float(close)

    serie, aportes = [], {s: [] for s in syms}
    completos = 0
    for f in sorted(por_dia):
        precios = por_dia[f]
        if len(precios) != len(syms):
            continue                      # dia incompleto: no se inventa
        completos += 1
        total = 0.0
        for s in syms:
            ap = precios[s] * factores[s]
            aportes[s].append(ap)
            total += ap
        serie.append([str(f), round(total, 4)])

    ultimo = {s: (aportes[s][-1] if aportes[s] else None) for s in syms}
    total_ultimo = sum(v for v in ultimo.values() if v) or 1.0
    return {
        "basket": name,
        "output_unit": c.output_unit,
        "series": serie,
        "days_complete": completos,
        "days_seen": len(por_dia),
        "components": [
            {
                "symbol": x.symbol, "name": x.nombre,
                "qty": x.qty, "qty_unit": x.qty_unit,
                "qty_price_unit": round(x.qty_en_unidad_de_precio, 6),
                "price_unit": x.price_unit,
                "cost": ultimo[x.symbol],
                # Exposicion: cuanto del costo de hoy depende de este insumo.
                "share_pct": (ultimo[x.symbol] / total_ultimo * 100) if ultimo[x.symbol] else None,
            }
            for x in c.componentes
        ],
    }


def escenario(name: str, shocks: dict[str, float], *, dsn: str = DSN) -> dict:
    """Cuanto cambia el costo si cada insumo se mueve el % indicado.

    `shocks`: {symbol: variacion_pct}. Los insumos sin shock quedan quietos.

    **Lo que este calculo NO hace:** propagar el shock a los demas insumos usando la
    correlacion. Si el cobre sube 10%, historicamente el aluminio tiende a acompanar —
    pero aplicar eso automaticamente convertiria un escenario explicito en una prediccion
    encubierta. El panel muestra las correlaciones al lado para que la decision la tome
    una persona.
    """
    base = serie_costo(name, days=30, dsn=dsn)
    comps = {c["symbol"]: c for c in base["components"]}
    if not comps or not base["series"]:
        return {"basket": name, "error": "sin datos"}

    costo_base = base["series"][-1][1]
    detalle, nuevo = [], 0.0
    for s, c in comps.items():
        pct = float(shocks.get(s, 0.0))
        antes = c["cost"] or 0.0
        despues = antes * (1 + pct / 100)
        nuevo += despues
        detalle.append({
            "symbol": s, "shock_pct": pct, "cost_before": antes,
            "cost_after": despues, "delta": despues - antes,
        })

    return {
        "basket": name,
        "cost_before": costo_base,
        "cost_after": round(nuevo, 4),
        "delta": round(nuevo - costo_base, 4),
        "delta_pct": round((nuevo / costo_base - 1) * 100, 3) if costo_base else None,
        "components": sorted(detalle, key=lambda d: -abs(d["delta"])),
        "nota": ("Los insumos sin shock quedan quietos. Este calculo NO propaga el "
                 "movimiento a los demas via correlacion: eso convertiria un escenario "
                 "explicito en una prediccion encubierta."),
    }


def listar(*, dsn: str = DSN) -> list[dict]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""SELECT b.name, b.description, b.output_unit, count(i.*)
                         FROM core.basket b LEFT JOIN core.basket_item i ON i.basket=b.name
                        GROUP BY 1,2,3 ORDER BY 1""")
        return [{"name": n, "description": d, "output_unit": u, "items": k}
                for n, d, u, k in cur.fetchall()]
