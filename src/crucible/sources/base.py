"""Contract for a data source.

The ingester talks ONLY to this interface. Switching to a paid feed, or to real LME data, is
writing a class — not rewriting the system. That is what makes it honest to use Yahoo's
chart API, which is unofficial and carries no service contract: fine for a portfolio, and
the day production is needed it gets replaced without touching anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SourceError(RuntimeError):
    """The source returned no usable data. Nothing is ever written after one of these."""


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class SourceAdapter(Protocol):
    name: str

    def display_name(self, ticker: str) -> str:
        """The name the source gives the instrument. Compared against `expect_name`."""
        ...

    def fetch(self, ticker: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        ...
