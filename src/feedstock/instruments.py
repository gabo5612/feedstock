"""Instrument registry.

**The field that matters is `expect_name`.** Every instrument declares a fragment that MUST
appear in the name the source returns. If it does not, ingestion fails and not a single row
is written.

The reason, verified on 2026-09-02 and again today: `ZN=F` **is not zinc**. It is the
10-year Treasury note future, and Yahoo returns it without any error. Putting it into a
metals dataset would have contaminated the whole model **without a single signal that
anything was wrong** — the kind of bug you cannot find by reading code, only by comparing
against the source.

That is why the registry stores the verified name, not the bare ticker.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str            # internal, stable name
    source: str
    source_ticker: str
    expect_name: str       # fragment that must appear in the source's name
    asset_class: str
    unit: str | None = None
    currency: str = "USD"


# The 12 from §1 of the spec, all verified without an API key.
INSTRUMENTS: tuple[Instrument, ...] = (
    # ── metals: the input cost that decides the plant's margin
    Instrument("copper",    "yahoo", "HG=F",      "Copper",    "metal", "USD/lb"),
    Instrument("gold",      "yahoo", "GC=F",      "Gold",      "metal", "USD/oz"),
    Instrument("silver",    "yahoo", "SI=F",      "Silver",    "metal", "USD/oz"),
    Instrument("aluminium", "yahoo", "ALI=F",     "Aluminum",  "metal", "USD/t"),
    Instrument("platinum",  "yahoo", "PL=F",      "Platinum",  "metal", "USD/oz"),
    Instrument("palladium", "yahoo", "PA=F",      "Palladium", "metal", "USD/oz"),
    # ── energy: the other large input for a metals plant
    Instrument("natgas",    "yahoo", "NG=F",      "Natural Gas", "energy", "USD/MMBtu"),
    Instrument("crude_wti", "yahoo", "CL=F",      "Crude Oil",   "energy", "USD/bbl"),
    # ── macro: moves the price of everything above
    Instrument("dxy",       "yahoo", "DX-Y.NYB",  "Dollar",    "fx"),
    Instrument("usdcny",    "yahoo", "USDCNY=X",  "USD/CNY",   "fx"),
    Instrument("eurusd",    "yahoo", "EURUSD=X",  "USD",       "fx"),
    # ── industrial-metals proxy: real LME data is paid
    Instrument("copper_miners_etf", "yahoo", "COPX", "Copper", "equity_proxy"),
)

BY_SYMBOL = {i.symbol: i for i in INSTRUMENTS}

# Tickers that look like something they are not. Written down so nobody adds them
# "because the name fits".
TRAPS = {
    "ZN=F": "NOT zinc: it is the 10-year Treasury note future (10-Year T-Note).",
}
