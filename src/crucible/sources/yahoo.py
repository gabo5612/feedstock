"""Adaptador de la chart API de Yahoo Finance.

Es no oficial y sin contrato de servicio. Para un proyecto de portfolio esta bien; para
produccion no. Por eso vive detras de `SourceAdapter`: cambiar a un feed pago —o al LME
real— es escribir otra clase, no reescribir el sistema.

**La trampa que este adaptador evita, verificada dos veces (2026-09-02 y 2026-09-06):**
`range=max&interval=1d` NO devuelve diario. Yahoo lo submuestrea a mensual **en silencio**:
268 puntos para 10 anos en vez de 2515. Sin error, sin aviso, sin nada. Un backfill hecho
asi produce un dataset que parece completo y no lo es, y todo lo que se entrene encima
hereda el problema. Por eso se pagina con `period1`/`period2` por tramos.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from .base import Bar, SourceError

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
# Sin User-Agent, Yahoo responde vacio. No con un error: vacio.
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Tramo por request. Yahoo tolera varios anos por llamada en diario, pero trocear acotta
# el dano de un fallo: se reintenta un tramo, no diez anos.
TRAMO = timedelta(days=730)


class YahooAdapter:
    name = "yahoo"

    def __init__(self, *, timeout: float = 30.0, pausa: float = 0.4, reintentos: int = 3):
        self._timeout = timeout
        self._pausa = pausa          # cortesia con la fuente, no es opcional
        self._reintentos = reintentos

    def _get(self, url: str) -> dict:
        ultimo: Exception | None = None
        for intento in range(self._reintentos):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=self._timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                ultimo = exc
                time.sleep(self._pausa * (2**intento))   # backoff exponencial
        raise SourceError(f"Yahoo no respondio tras {self._reintentos} intentos: {ultimo}")

    def display_name(self, ticker: str) -> str:
        """Nombre que Yahoo le da al instrumento. Es lo que se compara contra el registro."""
        d = self._get(f"{BASE}{ticker}?range=1d&interval=1d")
        try:
            meta = d["chart"]["result"][0]["meta"]
        except (KeyError, IndexError, TypeError) as exc:
            raise SourceError(f"{ticker}: respuesta sin metadatos ({exc})") from exc
        nombre = meta.get("shortName") or meta.get("longName")
        if not nombre:
            raise SourceError(f"{ticker}: la fuente no da nombre; no se puede verificar")
        return str(nombre)

    def fetch(
        self, ticker: str, start: datetime, end: datetime, interval: str = "1d"
    ) -> list[Bar]:
        """Barras entre `start` y `end`, paginando por tramos."""
        barras: dict[datetime, Bar] = {}
        cursor = start
        while cursor < end:
            hasta = min(cursor + TRAMO, end)
            url = (
                f"{BASE}{ticker}?period1={int(cursor.timestamp())}"
                f"&period2={int(hasta.timestamp())}&interval={interval}"
            )
            for b in self._parse(ticker, self._get(url)):
                barras[b.ts] = b      # el solape entre tramos se deduplica solo
            cursor = hasta
            time.sleep(self._pausa)
        return [barras[k] for k in sorted(barras)]

    @staticmethod
    def _parse(ticker: str, payload: dict) -> list[Bar]:
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise SourceError(f"{ticker}: {chart['error']}")
        resultados = chart.get("result") or []
        if not resultados:
            return []
        r = resultados[0]
        stamps = r.get("timestamp") or []
        q = ((r.get("indicators") or {}).get("quote") or [{}])[0]

        def col(nombre: str) -> list:
            v = q.get(nombre) or []
            return list(v) + [None] * (len(stamps) - len(v))

        o, h, l, c, v = (col(x) for x in ("open", "high", "low", "close", "volume"))
        salida = []
        for i, ts in enumerate(stamps):
            # Una barra sin cierre no es una barra: es un hueco que la fuente devuelve
            # igual. Se descarta acá para que no entre como dato y despues haya que
            # adivinar si el None era real.
            if c[i] is None:
                continue
            salida.append(
                Bar(
                    ts=datetime.fromtimestamp(ts, tz=timezone.utc),
                    open=o[i], high=h[i], low=l[i], close=c[i], volume=v[i],
                )
            )
        return salida
