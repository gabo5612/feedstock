"""Monitor de calidad de datos. El hermano de `assay` para series de precios.

La infraestructura para detectar problemas ya existia —`is_gap`, `display_name_verified`,
`ingested_at`— pero **nadie la miraba**. Un dato malo que nadie mira es peor que un dato
que falta: el que falta se nota, el malo se usa.

Cuatro comprobaciones, cada una contra un modo de falla concreto y observado:

1. **Frescura** — ¿la fuente dejo de actualizar? Un instrumento congelado hace tres
   semanas sigue devolviendo un precio: el ultimo. Nada avisa.
2. **Huecos** — dias habiles sin vela. Un hueco conocido se maneja; uno silencioso se
   interpola sin querer y termina siendo una feature inventada.
3. **Deriva de nombre** — el ticker sigue igual pero la fuente ahora devuelve otra cosa.
   Es el modo de falla de `ZN=F`, pero apareciendo DESPUES de la ingesta inicial.
4. **Valores atipicos** — un cambio de mas de N sigmas en un dia. Puede ser un error de la
   fuente (un decimal corrido) **o una crisis real**, y el monitor NO puede distinguirlos:
   solo los marca para que los mire una persona.

   Esa distincion no es teorica. La primera version de este archivo afirmaba que un salto
   asi "suele ser un error de la fuente". Al revisar lo que encontro, los 5 del crudo
   resultaron ser **marzo y abril de 2020** — el desplome del COVID, incluido el dia de
   precios negativos. Eventos reales. El texto se corrigio: un monitor que etiqueta la
   historia como un bug es peor que no tener monitor, porque invita a "limpiar" datos
   buenos.

   Nunca se corrigen solos: tocar la capa cruda automaticamente destruye la trazabilidad.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")

DIAS_FRESCURA = 5       # dias habiles sin actualizar antes de avisar
SIGMAS_SALTO = 8.0      # umbral para marcar, no para juzgar


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
                                          "el instrumento no tiene ninguna vela"))
                continue

            # 1) frescura
            cur.execute(
                """SELECT (CURRENT_DATE - max(ts)::date) FROM core.bar WHERE symbol=%s""",
                (sym,))
            atraso = cur.fetchone()[0] or 0
            if atraso > DIAS_FRESCURA * 2:
                hallazgos.append(Hallazgo(sym, "desactualizado", "critical",
                    f"ultimo dato hace {atraso} dias ({ultimo}). La fuente dejo de reportar.",
                    float(atraso)))
            elif atraso > DIAS_FRESCURA:
                hallazgos.append(Hallazgo(sym, "desactualizado", "warning",
                    f"ultimo dato hace {atraso} dias ({ultimo})", float(atraso)))

            # 2) huecos marcados
            if huecos:
                hallazgos.append(Hallazgo(sym, "huecos", "warning",
                    f"{huecos} vela(s) sin cierre marcadas como hueco", float(huecos)))

            # 3) nombre nunca verificado
            if not verificado or not nombre:
                hallazgos.append(Hallazgo(sym, "sin_verificar", "critical",
                    "el nombre de la fuente nunca se verifico contra lo esperado"))

            # 4) saltos imposibles
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
                rango = f"{desde}" if desde == hasta else f"{desde} a {hasta}"
                hallazgos.append(Hallazgo(sym, "valor_atipico", "warning",
                    f"{cuenta} dia(s) sobre {SIGMAS_SALTO:g}σ (peor {peor:.1f}σ, {rango}). "
                    f"Puede ser un error de la fuente o una crisis real: el monitor no "
                    f"distingue. Miralo antes de decidir.", float(peor)))

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
