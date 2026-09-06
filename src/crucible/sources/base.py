"""Contrato de una fuente de datos.

El ingester habla SOLO con esta interfaz. Cambiar a un feed pago, o al LME real, es
escribir una clase — no reescribir el sistema. Es lo que hace honesto usar la chart API de
Yahoo, que es no oficial y sin contrato de servicio: sirve para un portfolio, y el dia que
haga falta produccion se reemplaza sin tocar nada mas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SourceError(RuntimeError):
    """La fuente no entrego datos usables. Nunca se escribe nada tras uno de estos."""


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
        """Nombre que la fuente da al instrumento. Se compara contra `expect_name`."""
        ...

    def fetch(self, ticker: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        ...
