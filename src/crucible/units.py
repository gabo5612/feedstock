"""Conversion de unidades. Explicita, y falla fuerte ante lo desconocido.

El cobre cotiza en USD/lb y una planta piensa en kg. Una conversion implicita 1:1 daria un
costo **2.2 veces equivocado sin producir ningun error** — el mismo tipo de bug que
`ZN=F`: plausible, silencioso y contaminante.

Por eso el diccionario es chico y cerrado: si aparece un par que no esta, se levanta
`UnitError` en vez de asumir nada.
"""

from __future__ import annotations


class UnitError(ValueError):
    """No hay conversion conocida. Mejor un error que un numero inventado."""


# A la unidad canonica de cada familia.
_A_CANONICA: dict[str, tuple[str, float]] = {
    # masa → kilogramo
    "kg": ("kg", 1.0), "g": ("kg", 0.001), "t": ("kg", 1000.0),
    "tonelada": ("kg", 1000.0), "lb": ("kg", 0.45359237), "oz": ("kg", 0.028349523125),
    # onza TROY, la de los metales preciosos: 31.1035 g, NO la avoirdupois de 28.35.
    # Confundirlas da un 10% de error en oro y plata.
    "ozt": ("kg", 0.0311034768),
    # energia → MMBtu
    "MMBtu": ("MMBtu", 1.0), "MWh": ("MMBtu", 3.412142), "kWh": ("MMBtu", 0.003412142),
    # sin unidad (indices, tipos de cambio, ETF)
    "unidad": ("unidad", 1.0),
}


def convertir(qty: float, desde: str, hacia: str) -> float:
    """Cantidad expresada en `hacia`. Levanta si las familias no coinciden."""
    if desde == hacia:
        return qty
    a, b = _A_CANONICA.get(desde), _A_CANONICA.get(hacia)
    if a is None:
        raise UnitError(f"unidad desconocida: {desde!r}")
    if b is None:
        raise UnitError(f"unidad desconocida: {hacia!r}")
    if a[0] != b[0]:
        raise UnitError(
            f"no se puede convertir {desde!r} a {hacia!r}: son magnitudes distintas "
            f"({a[0]} vs {b[0]})"
        )
    return qty * a[1] / b[1]


def unidad_de_precio(unit: str | None) -> str:
    """De 'USD/lb' saca 'lb'. Sin unidad declarada, el instrumento se cotiza por unidad."""
    if not unit or "/" not in unit:
        return "unidad"
    u = unit.split("/", 1)[1].strip()
    # Los metales preciosos cotizan en onza troy aunque la fuente escriba solo "oz".
    return {"oz": "ozt"}.get(u, u)
