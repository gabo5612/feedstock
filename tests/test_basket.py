"""Unit and basket tests. The unit ones do not touch the database."""

import pytest

from feedstock.units import UnitError, convert, price_unit


def test_mass():
    assert convert(1, "kg", "lb") == pytest.approx(2.20462, rel=1e-4)
    assert convert(1, "t", "kg") == 1000
    assert convert(1000, "g", "kg") == 1


def test_the_troy_ounce_is_not_the_common_ounce():
    """31.1035 g against 28.35. Confusing them puts a 10% error into gold and silver."""
    assert convert(1, "ozt", "kg") == pytest.approx(0.0311035, rel=1e-4)
    assert convert(1, "oz", "kg") == pytest.approx(0.0283495, rel=1e-4)
    assert convert(1, "ozt", "kg") != convert(1, "oz", "kg")


def test_energy():
    assert convert(1, "MWh", "MMBtu") == pytest.approx(3.412142, rel=1e-5)


def test_it_does_not_convert_between_different_magnitudes():
    """A kg is not MWh. Better an error than an invented cost."""
    with pytest.raises(UnitError, match="different magnitudes"):
        convert(1, "kg", "MWh")


def test_an_unknown_unit_fails():
    with pytest.raises(UnitError, match="unknown"):
        convert(1, "kg", "quintal")


def test_round_trip():
    assert convert(convert(340, "kg", "lb"), "lb", "kg") == pytest.approx(340)


@pytest.mark.parametrize("unit,esperado", [
    ("USD/lb", "lb"), ("USD/t", "t"), ("USD/MMBtu", "MMBtu"),
    ("USD/oz", "ozt"),        # precious metals trade in troy ounces
    (None, "unit"), ("USD", "unit"),
])
def test_price_unit(unit, esperado):
    assert price_unit(unit) == esperado
