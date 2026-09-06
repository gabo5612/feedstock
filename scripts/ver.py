"""Quick inspection of what was ingested, without fighting docker or psql.

    python3 scripts/ver.py                  # summary of all 12 instruments
    python3 scripts/ver.py copper           # last 20 copper candles
    python3 scripts/ver.py copper 60        # last 60
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psycopg  # noqa: E402

DSN = os.environ.get("CRUCIBLE_DSN", "postgresql://crucible:crucible@localhost:5434/crucible")


def summary(cur) -> None:
    cur.execute("""
        SELECT i.symbol, i.display_name_verified, i.asset_class,
               count(b.*), min(b.ts)::date, max(b.ts)::date,
               count(*) FILTER (WHERE b.is_gap)
          FROM core.instrument i
          LEFT JOIN core.bar b ON b.symbol = i.symbol
         GROUP BY 1,2,3 ORDER BY 1""")
    print(f"\n{'instrument':<18}{'verified name':<28}{'class':<14}{'candles':>7}"
          f"{'gaps':>8}  range")
    print("─" * 100)
    for sym, name, cls, n, first, last, gaps in cur.fetchall():
        rng = f"{first} → {last}" if first else "—"
        print(f"{sym:<18}{(name or '')[:26]:<28}{cls:<14}{n:>7}{gaps:>8}  {rng}")
    print("─" * 100)
    cur.execute("SELECT count(*) FROM raw.ohlcv_ingest")
    print(f"{cur.fetchone()[0]} rows in raw (the raw layer, never modified)\n")


def candles(cur, symbol: str, n: int) -> None:
    cur.execute(
        "SELECT display_name_verified FROM core.instrument WHERE symbol=%s", (symbol,)
    )
    row = cur.fetchone()
    if not row:
        print(f"\n'{symbol}' does not exist. Run without arguments to list what is available.\n")
        return
    print(f"\n{symbol} — {row[0]}   (last {n} candles)")
    print(f"\n{'date':<14}{'open':>11}{'high':>11}{'low':>11}{'close':>11}")
    print("─" * 58)
    cur.execute(
        """SELECT ts::date, open, high, low, close FROM core.bar
            WHERE symbol=%s AND interval='1d' ORDER BY ts DESC LIMIT %s""",
        (symbol, n),
    )
    for f, o, h, l, c in cur.fetchall():
        fmt = lambda v: "—" if v is None else f"{v:,.4f}".rstrip("0").rstrip(".")
        print(f"{str(f):<14}{fmt(o):>11}{fmt(h):>11}{fmt(l):>11}{fmt(c):>11}")
    print("\nCheck it against finance.yahoo.com: it has to match.\n")


def main(argv: list[str]) -> int:
    try:
        with psycopg.connect(DSN, connect_timeout=5) as conn, conn.cursor() as cur:
            if argv:
                candles(cur, argv[0], int(argv[1]) if len(argv) > 1 else 20)
            else:
                summary(cur)
    except psycopg.OperationalError as exc:
        print(f"\nCould not connect to the database: {exc}")
        print("Is it running?  cd crucible && docker-compose up -d\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
