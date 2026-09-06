"""Adapter for the Yahoo Finance chart API.

It is unofficial and carries no service contract. Fine for a portfolio project; not for
production. Hence it lives behind `SourceAdapter`: switching to a paid feed — or to real
LME data — is writing another class, not rewriting the system.

**The trap this adapter avoids, verified twice (2026-09-02 and 2026-09-06):**
`range=max&interval=1d` does NOT return daily data. Yahoo downsamples it to monthly
**silently**: 268 points over 10 years instead of 2,515. No error, no warning, nothing. A
backfill built that way produces a dataset that looks complete and is not, and everything
trained on top inherits the problem. That is why it paginates with `period1`/`period2`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from .base import Bar, SourceError

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
# Without a User-Agent, Yahoo responds empty. Not with an error: empty.
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Chunk per request. Yahoo tolerates several years per daily call, but chunking bounds the
# damage of a failure: you retry one chunk, not ten years.
CHUNK = timedelta(days=730)


class YahooAdapter:
    name = "yahoo"

    def __init__(self, *, timeout: float = 30.0, pause: float = 0.4, retries: int = 3):
        self._timeout = timeout
        self._pause = pause          # courtesy toward the source, not optional
        self._retries = retries

    def _get(self, url: str) -> dict:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=self._timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(self._pause * (2**attempt))   # exponential backoff
        raise SourceError(f"Yahoo did not respond after {self._retries} attempts: {last}")

    def display_name(self, ticker: str) -> str:
        """The name Yahoo gives the instrument. This is what is compared to the registry."""
        d = self._get(f"{BASE}{ticker}?range=1d&interval=1d")
        try:
            meta = d["chart"]["result"][0]["meta"]
        except (KeyError, IndexError, TypeError) as exc:
            raise SourceError(f"{ticker}: response without metadata ({exc})") from exc
        name = meta.get("shortName") or meta.get("longName")
        if not name:
            raise SourceError(f"{ticker}: the source gives no name; it cannot be verified")
        return str(name)

    def fetch(
        self, ticker: str, start: datetime, end: datetime, interval: str = "1d"
    ) -> list[Bar]:
        """Bars between `start` and `end`, paginated in chunks."""
        bars: dict[datetime, Bar] = {}
        cursor = start
        while cursor < end:
            until = min(cursor + CHUNK, end)
            url = (
                f"{BASE}{ticker}?period1={int(cursor.timestamp())}"
                f"&period2={int(until.timestamp())}&interval={interval}"
            )
            for b in self._parse(ticker, self._get(url)):
                bars[b.ts] = b      # overlap between chunks deduplicates itself
            cursor = until
            time.sleep(self._pause)
        return [bars[k] for k in sorted(bars)]

    @staticmethod
    def _parse(ticker: str, payload: dict) -> list[Bar]:
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise SourceError(f"{ticker}: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            return []
        r = results[0]
        stamps = r.get("timestamp") or []
        q = ((r.get("indicators") or {}).get("quote") or [{}])[0]

        def col(nombre: str) -> list:
            v = q.get(nombre) or []
            return list(v) + [None] * (len(stamps) - len(v))

        o, h, l, c, v = (col(x) for x in ("open", "high", "low", "close", "volume"))
        out = []
        for i, ts in enumerate(stamps):
            # A bar without a close is not a bar: it is a gap the source returns anyway.
            # Dropped here so it does not enter as data and leave someone later guessing
            # whether the None was real.
            if c[i] is None:
                continue
            out.append(
                Bar(
                    ts=datetime.fromtimestamp(ts, tz=timezone.utc),
                    open=o[i], high=h[i], low=l[i], close=c[i], volume=v[i],
                )
            )
        return out
