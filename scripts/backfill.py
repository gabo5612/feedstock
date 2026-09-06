"""10-year backfill. Prints a report of rows and gaps per instrument.

    python3 scripts/backfill.py            # all 12 instruments
    python3 scripts/backfill.py copper     # just one
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crucible.ingest import backfill  # noqa: E402
from crucible.instruments import INSTRUMENTS  # noqa: E402
from crucible.sources import YahooAdapter  # noqa: E402


def main(argv: list[str]) -> int:
    symbols = argv or [i.symbol for i in INSTRUMENTS]
    reportes = backfill(YahooAdapter(), symbols, years=10)

    print(f"\n{'instrument':<18}{'verified name':<26}{'rows':>7}{'new':>8}"
          f"{'gaps':>8}  range")
    print("─" * 104)
    failures = 0
    for r in reportes:
        if r.error:
            failures += 1
            print(f"{r.symbol:<18}✗ {r.error[:78]}")
            continue
        total = r.rows_inserted + r.rows_skipped
        rng = (f"{r.first_ts:%Y-%m-%d} → {r.last_ts:%Y-%m-%d}"
               if r.first_ts and r.last_ts else "—")
        print(f"{r.symbol:<18}{r.source_name[:24]:<26}{total:>7}{r.rows_inserted:>8}"
              f"{r.gaps:>8}  {rng}")
    print("─" * 104)
    ok = [r for r in reportes if not r.error]
    print(f"{len(ok)} instrument(s) ingested · {failures} with errors · "
          f"{sum(r.rows_inserted for r in ok)} new rows\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
