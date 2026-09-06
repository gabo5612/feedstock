"""Registro de instrumentos.

**El campo que importa es `expect_name`.** Cada instrumento declara un fragmento que TIENE
que aparecer en el nombre que devuelve la fuente. Si no aparece, la ingesta falla y no
escribe una sola fila.

La razon, verificada el 2026-09-02 y otra vez hoy: `ZN=F` **no es zinc**. Es el futuro del
bono del Tesoro a 10 anos, y Yahoo lo devuelve sin ningun error. Meterlo en un dataset de
metales habria contaminado el modelo entero **sin una sola senal de que algo anda mal** —
el tipo de bug que no se encuentra mirando codigo, solo comparando contra la fuente.

Por eso el registro guarda el nombre verificado, no el ticker a secas.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str            # nombre interno, estable
    source: str
    source_ticker: str
    expect_name: str       # fragmento que debe aparecer en el nombre de la fuente
    asset_class: str
    unit: str | None = None
    currency: str = "USD"


# Los 12 del spec §1, todos verificados sin API key.
INSTRUMENTS: tuple[Instrument, ...] = (
    # ── metales: el costo de insumo que decide el margen de la planta
    Instrument("copper",    "yahoo", "HG=F",      "Copper",    "metal", "USD/lb"),
    Instrument("gold",      "yahoo", "GC=F",      "Gold",      "metal", "USD/oz"),
    Instrument("silver",    "yahoo", "SI=F",      "Silver",    "metal", "USD/oz"),
    Instrument("aluminium", "yahoo", "ALI=F",     "Aluminum",  "metal", "USD/t"),
    Instrument("platinum",  "yahoo", "PL=F",      "Platinum",  "metal", "USD/oz"),
    Instrument("palladium", "yahoo", "PA=F",      "Palladium", "metal", "USD/oz"),
    # ── energia: el otro insumo grande de una metalurgica
    Instrument("natgas",    "yahoo", "NG=F",      "Natural Gas", "energy", "USD/MMBtu"),
    Instrument("crude_wti", "yahoo", "CL=F",      "Crude Oil",   "energy", "USD/bbl"),
    # ── macro: mueve el precio de todo lo de arriba
    Instrument("dxy",       "yahoo", "DX-Y.NYB",  "Dollar",    "fx"),
    Instrument("usdcny",    "yahoo", "USDCNY=X",  "USD/CNY",   "fx"),
    Instrument("eurusd",    "yahoo", "EURUSD=X",  "USD",       "fx"),
    # ── proxy de metales industriales: el LME real es de pago
    Instrument("copper_miners_etf", "yahoo", "COPX", "Copper", "equity_proxy"),
)

BY_SYMBOL = {i.symbol: i for i in INSTRUMENTS}

# Tickers que parecen lo que no son. Se dejan escritos para que nadie los agregue
# "porque el nombre calza".
TRAMPAS = {
    "ZN=F": "NO es zinc: es el futuro del bono del Tesoro a 10 anos (10-Year T-Note).",
}
