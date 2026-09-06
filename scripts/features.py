"""Calcula y persiste las features de todos los instrumentos."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from crucible.features import compute_all  # noqa: E402
from crucible.instruments import INSTRUMENTS  # noqa: E402

syms = sys.argv[1:] or [i.symbol for i in INSTRUMENTS]
print(f"\n{'instrumento':<20}{'filas de feature':>18}")
print("─" * 40)
total = 0
for r in compute_all(syms):
    total += r.rows
    print(f"{r.symbol:<20}{r.rows:>18,}")
print("─" * 40)
print(f"{'TOTAL':<20}{total:>18,}\n")
if syms:
    from crucible.features import compute
    print("features por instrumento:", ", ".join(compute(syms[0], persist=False).names), "\n")
