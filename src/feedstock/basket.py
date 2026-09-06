"""Cost basket, exposure and scenarios.

Answers the question a plant actually has: **what does one unit cost me to produce, how did
that cost evolve, and which input moved it.** A chart of commodity prices does not answer
that; a basket does.

Three things come out of the same computation:
  · **cost**      — the unit-cost series over time
  · **exposure**  — how much each input weighs in today's cost
  · **scenario**  — how much the cost changes if one input moves X%
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import psycopg

from .units import convert, price_unit

DSN = os.environ.get("FEEDSTOCK_DSN", "postgresql://feedstock:feedstock@localhost:5434/feedstock")


@dataclass
class Componente:
    symbol: str
    nombre: str
    qty: float
    qty_unit: str
    price_unit: str
    qty_in_price_unit: float
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
    """`items`: [{symbol, qty, qty_unit, nota?}]. Validates units BEFORE saving."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # Validation comes first: a half-saved basket with an impossible unit is worse
        # than an error.
        for it in items:
            cur.execute("SELECT unit FROM core.instrument WHERE symbol=%s", (it["symbol"],))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"{it['symbol']} is not in the instrument registry")
            convert(float(it["qty"]), it["qty_unit"], price_unit(row[0]))

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
            up = price_unit(punit)
            comps.append(Componente(
                symbol=sym, nombre=nombre, qty=float(qty), qty_unit=qunit,
                price_unit=up, qty_in_price_unit=convert(float(qty), qunit, up)))
    return Canasta(name=cab[0], description=cab[1], output_unit=cab[2], componentes=comps)


def serie_costo(name: str, *, days: int = 365, dsn: str = DSN) -> dict:
    """Unit cost, day by day.

    A day is only computed if ALL inputs traded that day. Filling the missing one with the
    last known price would produce a series that looks continuous and hides the fact that an
    input stopped reporting — the same criterion as flagging gaps in `core.bar`.
    """
    c = cargar(name, dsn=dsn)
    if not c or not c.componentes:
        return {"basket": name, "series": [], "components": []}

    syms = [x.symbol for x in c.componentes]
    factors = {x.symbol: x.qty_in_price_unit for x in c.componentes}

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT ts::date, symbol, close FROM core.bar
                WHERE symbol = ANY(%s) AND interval='1d' AND close IS NOT NULL
                  AND ts >= now() - (%s || ' days')::interval
                ORDER BY ts""", (syms, days))
        by_day: dict = {}
        for f, sym, close in cur.fetchall():
            by_day.setdefault(f, {})[sym] = float(close)

    series, contributions = [], {s: [] for s in syms}
    complete = 0
    for f in sorted(by_day):
        prices = by_day[f]
        if len(prices) != len(syms):
            continue                      # incomplete day: nothing is invented
        complete += 1
        total = 0.0
        for s in syms:
            contribution = prices[s] * factors[s]
            contributions[s].append(contribution)
            total += contribution
        series.append([str(f), round(total, 4)])

    last = {s: (contributions[s][-1] if contributions[s] else None) for s in syms}
    last_total = sum(v for v in last.values() if v) or 1.0
    return {
        "basket": name,
        "output_unit": c.output_unit,
        "series": series,
        "days_complete": complete,
        "days_seen": len(by_day),
        "components": [
            {
                "symbol": x.symbol, "name": x.nombre,
                "qty": x.qty, "qty_unit": x.qty_unit,
                "qty_price_unit": round(x.qty_in_price_unit, 6),
                "price_unit": x.price_unit,
                "cost": last[x.symbol],
                # Exposure: how much of today's cost depends on this input.
                "share_pct": (last[x.symbol] / last_total * 100) if last[x.symbol] else None,
            }
            for x in c.componentes
        ],
    }


def escenario(name: str, shocks: dict[str, float], *, dsn: str = DSN) -> dict:
    """How much the cost changes if each input moves by the given %.

    `shocks`: {symbol: pct_change}. Inputs without a shock stay put.

    **What this computation does NOT do:** propagate the shock to the other inputs using
    correlation. If copper rises 10%, aluminium historically tends to follow — but applying
    that automatically would turn an explicit scenario into a covert prediction. The panel
    shows the correlations alongside so a person makes that call.
    """
    base = serie_costo(name, days=30, dsn=dsn)
    comps = {c["symbol"]: c for c in base["components"]}
    if not comps or not base["series"]:
        return {"basket": name, "error": "sin datos"}

    base_cost = base["series"][-1][1]
    detail, new_cost = [], 0.0
    for s, c in comps.items():
        pct = float(shocks.get(s, 0.0))
        before = c["cost"] or 0.0
        after = before * (1 + pct / 100)
        new_cost += after
        detail.append({
            "symbol": s, "shock_pct": pct, "cost_before": before,
            "cost_after": after, "delta": after - before,
        })

    return {
        "basket": name,
        "cost_before": base_cost,
        "cost_after": round(new_cost, 4),
        "delta": round(new_cost - base_cost, 4),
        "delta_pct": round((new_cost / base_cost - 1) * 100, 3) if base_cost else None,
        "components": sorted(detail, key=lambda d: -abs(d["delta"])),
        "nota": ("Inputs without a shock stay put. This computation does NOT propagate the "
                 "move to the others via correlation: that would turn an explicit scenario "
                 "into a covert prediction."),
    }


def listar(*, dsn: str = DSN) -> list[dict]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""SELECT b.name, b.description, b.output_unit, count(i.*)
                         FROM core.basket b LEFT JOIN core.basket_item i ON i.basket=b.name
                        GROUP BY 1,2,3 ORDER BY 1""")
        return [{"name": n, "description": d, "output_unit": u, "items": k}
                for n, d, u, k in cur.fetchall()]
