"""Inspeccion rapida de lo ingerido, sin pelear con docker ni psql.

    python3 scripts/ver.py                  # resumen de los 12 instrumentos
    python3 scripts/ver.py copper           # ultimas 20 velas del cobre
    python3 scripts/ver.py copper 60        # ultimas 60
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psycopg  # noqa: E402

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")


def resumen(cur) -> None:
    cur.execute("""
        SELECT i.symbol, i.display_name_verified, i.asset_class,
               count(b.*), min(b.ts)::date, max(b.ts)::date,
               count(*) FILTER (WHERE b.is_gap)
          FROM core.instrument i
          LEFT JOIN core.bar b ON b.symbol = i.symbol
         GROUP BY 1,2,3 ORDER BY 1""")
    print(f"\n{'instrumento':<18}{'nombre verificado':<28}{'clase':<14}{'velas':>7}"
          f"{'huecos':>8}  rango")
    print("─" * 100)
    for sym, nombre, clase, n, ini, fin, huecos in cur.fetchall():
        rango = f"{ini} → {fin}" if ini else "—"
        print(f"{sym:<18}{(nombre or '')[:26]:<28}{clase:<14}{n:>7}{huecos:>8}  {rango}")
    print("─" * 100)
    cur.execute("SELECT count(*) FROM raw.ohlcv_ingest")
    print(f"{cur.fetchone()[0]} filas en raw (la capa cruda, que nunca se modifica)\n")


def velas(cur, symbol: str, n: int) -> None:
    cur.execute(
        "SELECT display_name_verified FROM core.instrument WHERE symbol=%s", (symbol,)
    )
    fila = cur.fetchone()
    if not fila:
        print(f"\n'{symbol}' no existe. Corre sin argumentos para ver los disponibles.\n")
        return
    print(f"\n{symbol} — {fila[0]}   (ultimas {n} velas)")
    print(f"\n{'fecha':<14}{'apertura':>11}{'maximo':>11}{'minimo':>11}{'cierre':>11}")
    print("─" * 58)
    cur.execute(
        """SELECT ts::date, open, high, low, close FROM core.bar
            WHERE symbol=%s AND interval='1d' ORDER BY ts DESC LIMIT %s""",
        (symbol, n),
    )
    for f, o, h, l, c in cur.fetchall():
        fmt = lambda v: "—" if v is None else f"{v:,.4f}".rstrip("0").rstrip(".")
        print(f"{str(f):<14}{fmt(o):>11}{fmt(h):>11}{fmt(l):>11}{fmt(c):>11}")
    print("\nContrastalo contra finance.yahoo.com: tiene que dar igual.\n")


def main(argv: list[str]) -> int:
    try:
        with psycopg.connect(DSN, connect_timeout=5) as conn, conn.cursor() as cur:
            if argv:
                velas(cur, argv[0], int(argv[1]) if len(argv) > 1 else 20)
            else:
                resumen(cur)
    except psycopg.OperationalError as exc:
        print(f"\nNo pude conectar a la base: {exc}")
        print("¿Esta levantada?  cd crucible && docker-compose up -d\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
