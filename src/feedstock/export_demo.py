"""Exports a static bundle of the real database so the demo runs with no backend.

What travels and what does NOT:
  YES  the instrument registry, with the display names verified against the source
  YES  every daily bar (date, close, high, low) -> the browser recomputes series,
       statistics and correlations from the same numbers the API reads
  YES  signals, baskets, alerts and the data-quality report, as the server computes them
  NO   the ingester and the database -> Vercel has neither, and the point of the project
       is that they run inside the plant

`reference` carries answers computed here, by the server code, for a handful of cases.
`demo/verify.mjs` recomputes those same cases with the browser port and fails if any of
them disagrees, so the page cannot quietly show numbers the backend never produced.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

DSN = os.environ.get("FEEDSTOCK_DSN", "postgresql://feedstock:feedstock@localhost:5434/feedstock")
RANGES = (90, 365, 1095, 1825, 3650)
HORIZON = 60


def _bars(dsn: str) -> dict[str, list]:
    """Daily bars as `[epoch_seconds, close, high, low]`.

    The instant, not the date: a bar is stamped at 04:00 UTC for a future and at 21:00 for
    a currency pair, and the API filters with `ts >= now - days`. Exporting `ts::date`
    would move the window boundary by a day for FX and every aggregate downstream with it.
    """
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("""
            SELECT symbol, extract(epoch FROM ts)::bigint, close, high, low
              FROM core.bar
             WHERE interval='1d' AND close IS NOT NULL
             ORDER BY symbol, ts""")
        out: dict[str, list] = {}
        for sym, epoch, close, high, low in cur.fetchall():
            out.setdefault(sym, []).append(
                [epoch, float(close),
                 None if high is None else float(high),
                 None if low is None else float(low)]
            )
    return out


def build(dsn: str = DSN) -> dict[str, Any]:
    from .alerts import historial, listar as listar_alertas
    from .api.main import correlation, instruments, stats
    from .basket import listar as listar_canastas, serie_costo
    from .quality import revisar
    from .signals import recomendacion

    insts = instruments()
    symbols = [i["symbol"] for i in insts]
    bars = _bars(dsn)

    baskets = listar_canastas()
    basket_series = {
        f"{b['name']}|{days}": serie_costo(b["name"], days=days)
        for b in baskets for days in RANGES
    }

    # Reference answers, computed by the server code, for the cases verify.mjs replays.
    metals = [i["symbol"] for i in insts if i["asset_class"] == "metal"][:4]
    reference = {
        "stats": {f"{s}|{d}": stats(s, days=d) for s in symbols for d in (90, 365)},
        "correlation": {
            f"{','.join(metals)}|365": correlation(",".join(metals), days=365),
            f"{','.join(symbols[:6])}|1095": correlation(",".join(symbols[:6]), days=1095),
        },
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ranges": list(RANGES),
        "horizon": HORIZON,
        "instruments": insts,
        "bars": bars,
        "signals": [recomendacion(s, horizonte=HORIZON) for s in symbols],
        "baskets": baskets,
        "basket_series": basket_series,
        "alerts": listar_alertas(),
        "alerts_history": historial(limite=40),
        "quality": revisar(),
        "reference": reference,
    }


BANNER = """    <div class="card" style="border-left:4px solid var(--acc,#4c8dff)">
      <h2>Static demo</h2>
      <p class="note">The real system runs <b>inside the plant</b>: an ingester, TimescaleDB and
      an API. Vercel has none of that, so this copy carries <b>the real database exported</b> —
      every daily bar, the signals, the basket and the data-quality report — and answers the
      dashboard's own API calls from it. Series, statistics and correlations are
      <b>recomputed in your browser</b> from those bars, ported from the SQL; a check
      (<code>node verify.mjs</code>) diffs them against the backend's answers so the page cannot
      show numbers the backend never produced. The window is anchored to the export date.</p>
    </div>

"""

SHIM = """<script>
/* Defers every /api/ call to the static export. Classic script on purpose: it has to be in
   place before the dashboard's own script runs, while the data and the port load async. */
(function () {
  const data = fetch('./data.json').then(r => r.json());
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.origin);
    if (!url.pathname.startsWith('/api/')) return real(input, init);
    const [mod, d] = await Promise.all([import('./offline.js'), data]);
    return mod.respond(d, url, init);
  };
})();
</script>
"""


def render_index(web: Path, out: Path) -> int:
    """Builds demo/index.html from the app's own UI, so the demo cannot drift from it."""
    html = web.read_text(encoding="utf-8")
    if "<main>" not in html or "<script>" not in html:
        raise RuntimeError("the UI no longer has the anchors this build relies on")
    html = html.replace("  <main>\n", "  <main>\n" + BANNER, 1)
    html = html.replace("<script>", SHIM + "<script>", 1)
    html = html.replace(
        "Could not read the database.<br>Did you run <code>docker-compose up -d</code>?",
        "Could not load the exported dataset.",
    )
    out.write_text(html, encoding="utf-8")
    return len(html)


def export(out: Path, dsn: str = DSN) -> dict[str, Any]:
    data = build(dsn)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str),
                   encoding="utf-8")
    render_index(Path(__file__).resolve().parent / "web" / "index.html", out.parent / "index.html")
    return {
        "instruments": len(data["instruments"]),
        "bars": sum(len(v) for v in data["bars"].values()),
        "baskets": len(data["baskets"]),
        "alerts": len(data["alerts"]),
        "kb": round(out.stat().st_size / 1024),
    }


if __name__ == "__main__":
    print(export(Path(__file__).resolve().parents[2] / "demo" / "data.json"))
