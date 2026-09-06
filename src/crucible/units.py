"""Unit conversion. Explicit, and it fails loudly on anything unknown.

Copper trades in USD/lb and a plant thinks in kg. An implicit 1:1 conversion would give a
cost that is **2.2× wrong without producing any error** — the same class of bug as `ZN=F`:
plausible, silent and contaminating.

That is why the dictionary is small and closed: if a pair is not in it, `UnitError` is
raised rather than anything being assumed.
"""

from __future__ import annotations


class UnitError(ValueError):
    """No known conversion. Better an error than an invented number."""


# To each family's canonical unit.
_TO_CANONICAL: dict[str, tuple[str, float]] = {
    # mass → kilogram
    "kg": ("kg", 1.0), "g": ("kg", 0.001), "t": ("kg", 1000.0),
    "tonelada": ("kg", 1000.0), "lb": ("kg", 0.45359237), "oz": ("kg", 0.028349523125),
    # TROY ounce, the precious-metals one: 31.1035 g, NOT the 28.35 avoirdupois.
    # Confusing them puts a 10% error into gold and silver.
    "ozt": ("kg", 0.0311034768),
    # energy → MMBtu
    "MMBtu": ("MMBtu", 1.0), "MWh": ("MMBtu", 3.412142), "kWh": ("MMBtu", 0.003412142),
    # unitless (indices, exchange rates, ETFs)
    "unit": ("unit", 1.0),
}


def convert(qty: float, from_unit: str, to_unit: str) -> float:
    """Quantity expressed in `to_unit`. Raises if the families do not match."""
    if from_unit == to_unit:
        return qty
    a, b = _TO_CANONICAL.get(from_unit), _TO_CANONICAL.get(to_unit)
    if a is None:
        raise UnitError(f"unknown unit: {from_unit!r}")
    if b is None:
        raise UnitError(f"unknown unit: {to_unit!r}")
    if a[0] != b[0]:
        raise UnitError(
            f"cannot convert {from_unit!r} to {to_unit!r}: different magnitudes "
            f"({a[0]} vs {b[0]})"
        )
    return qty * a[1] / b[1]


def price_unit(unit: str | None) -> str:
    """From 'USD/lb' extracts 'lb'. With no declared unit, the instrument trades per unit."""
    if not unit or "/" not in unit:
        return "unit"
    u = unit.split("/", 1)[1].strip()
    # Precious metals trade in troy ounces even when the source only writes "oz".
    return {"oz": "ozt"}.get(u, u)
