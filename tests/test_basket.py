"""Tests de unidades y canasta. Los de unidades no tocan la base."""

import pytest

from crucible.units import UnitError, convertir, unidad_de_precio


def test_masa():
    assert convertir(1, "kg", "lb") == pytest.approx(2.20462, rel=1e-4)
    assert convertir(1, "t", "kg") == 1000
    assert convertir(1000, "g", "kg") == 1


def test_la_onza_troy_no_es_la_onza_comun():
    """31.1035 g contra 28.35. Confundirlas da 10% de error en oro y plata."""
    assert convertir(1, "ozt", "kg") == pytest.approx(0.0311035, rel=1e-4)
    assert convertir(1, "oz", "kg") == pytest.approx(0.0283495, rel=1e-4)
    assert convertir(1, "ozt", "kg") != convertir(1, "oz", "kg")


def test_energia():
    assert convertir(1, "MWh", "MMBtu") == pytest.approx(3.412142, rel=1e-5)


def test_no_convierte_entre_magnitudes_distintas():
    """Un kg no son MWh. Mejor un error que un costo inventado."""
    with pytest.raises(UnitError, match="magnitudes distintas"):
        convertir(1, "kg", "MWh")


def test_una_unidad_desconocida_falla():
    with pytest.raises(UnitError, match="desconocida"):
        convertir(1, "kg", "quintal")


def test_ida_y_vuelta():
    assert convertir(convertir(340, "kg", "lb"), "lb", "kg") == pytest.approx(340)


@pytest.mark.parametrize("unit,esperado", [
    ("USD/lb", "lb"), ("USD/t", "t"), ("USD/MMBtu", "MMBtu"),
    ("USD/oz", "ozt"),        # los metales preciosos cotizan en onza troy
    (None, "unidad"), ("USD", "unidad"),
])
def test_unidad_de_precio(unit, esperado):
    assert unidad_de_precio(unit) == esperado
