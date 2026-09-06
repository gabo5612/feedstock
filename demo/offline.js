// Serves the real API's shape from a static export, so the dashboard runs unmodified
// with no backend.
//
// Two kinds of answer live here:
//   · replayed  — signals, baskets, alerts and the quality report, exactly as the server
//                 computed them at export time
//   · recomputed — series, statistics and correlations, calculated in the browser from
//                 the same daily bars the API reads, porting the SQL one to one:
//                 stddev_samp, ln returns, corr over returns rather than prices
//
// `verify.mjs` replays the recomputed half against reference answers the Python code
// produced, so a drift in this file fails in CI instead of showing prettier numbers.
//
// The window is anchored to the export date, not to the visitor's clock: the API asks for
// `now - days`, and a demo whose window silently shrinks every day is not reproducible.

export function makeApi(data) {
  const NOW = new Date(data.generated_at);
  // `ts >= now - days` in SQL, compared as instants. A bar is stamped at 04:00 UTC for a
  // future and at 21:00 for a currency pair, so comparing calendar dates would shift the
  // window by a day for FX and drift every aggregate built on it.
  const barsSince = (symbol, days) => {
    const cutoff = NOW.getTime() / 1000 - days * 86400;
    return (data.bars[symbol] || []).filter((b) => b[0] >= cutoff);
  };
  const dayOf = (epoch) => new Date(epoch * 1000).toISOString().slice(0, 10);

  const stddevSamp = (xs) => {
    if (xs.length < 2) return null;
    const m = xs.reduce((a, b) => a + b, 0) / xs.length;
    return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1));
  };

  const logReturns = (rows) => {
    const out = [];
    for (let i = 1; i < rows.length; i++) {
      const [ts, close] = rows[i], prev = rows[i - 1][1];
      if (close > 0 && prev > 0) out.push([ts, Math.log(close / prev)]);
    }
    return out;
  };

  const corr = (xs, ys) => {
    const n = xs.length;
    if (n < 2) return null;
    const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
    let num = 0, dx = 0, dy = 0;
    for (let i = 0; i < n; i++) {
      const a = xs[i] - mx, b = ys[i] - my;
      num += a * b; dx += a * a; dy += b * b;
    }
    return dx && dy ? num / Math.sqrt(dx * dy) : null;
  };

  const routes = {
    instruments: () => data.instruments,

    series: (p) => {
      const symbols = (p.get("symbols") || "").split(",").map((s) => s.trim()).filter(Boolean);
      const days = Number(p.get("days") || 365);
      const series = {};
      for (const s of symbols) series[s] = barsSince(s, days).map((b) => [dayOf(b[0]), b[1]]);
      return { days, series };
    },

    stats: (p) => {
      const symbol = p.get("symbol");
      const days = Number(p.get("days") || 365);
      const rows = barsSince(symbol, days);
      if (!rows.length) return { error: `no data for ${symbol}` };
      const closes = rows.map((b) => b[1]);
      const lows = rows.map((b) => (b[3] ?? b[1]));
      const highs = rows.map((b) => (b[2] ?? b[1]));
      const rets = logReturns(rows).map((r) => r[1]);
      const sd = stddevSamp(rets);
      return {
        symbol, bars: rows.length,
        min: Math.min(...lows), max: Math.max(...highs),
        avg: closes.reduce((a, b) => a + b, 0) / closes.length,
        from: dayOf(rows[0][0]), to: dayOf(rows[rows.length - 1][0]),
        annualized_vol_pct: sd === null ? null : sd * Math.sqrt(252) * 100,
      };
    },

    correlation: (p) => {
      const symbols = (p.get("symbols") || "").split(",").map((s) => s.trim()).filter(Boolean);
      const days = Number(p.get("days") || 365);
      const byDate = new Map();
      for (const s of symbols) {
        for (const [d, r] of logReturns(barsSince(s, days))) {
          if (!byDate.has(d)) byDate.set(d, {});
          byDate.get(d)[s] = r;
        }
      }
      const matrix = [];
      for (const a of symbols) {
        for (const b of symbols) {
          const xs = [], ys = [];
          for (const row of byDate.values()) {
            if (row[a] !== undefined && row[b] !== undefined) { xs.push(row[a]); ys.push(row[b]); }
          }
          if (xs.length) matrix.push({ a, b, r: corr(xs, ys), n: xs.length });
        }
      }
      return { symbols, matrix };
    },

    signal: (p) => data.signals.find((s) => s.symbol === p.get("symbol")) || { error: "unknown symbol" },
    signals: () => data.signals,
    baskets: () => data.baskets,
    basket: (p) => data.basket_series[`${p.get("name")}|${p.get("days") || 365}`]
      || data.basket_series[`${p.get("name")}|365`],
    alerts: () => data.alerts,
    "alerts/history": () => data.alerts_history,
    quality: () => data.quality,
  };

  // Port of basket.escenario: apply the shock to each component's current cost and add
  // them back up. It deliberately does NOT propagate the move to the other inputs.
  function scenario(payload) {
    const base = data.basket_series[`${payload.name}|30`] || data.basket_series[`${payload.name}|90`];
    if (!base || !base.series?.length) return { basket: payload.name, error: "sin datos" };
    const shocks = payload.shocks || {};
    const costBefore = base.series[base.series.length - 1][1];
    let costAfter = 0;
    const components = base.components.map((c) => {
      const pct = Number(shocks[c.symbol] || 0);
      const before = c.cost || 0;
      const after = before * (1 + pct / 100);
      costAfter += after;
      return { symbol: c.symbol, shock_pct: pct, cost_before: before, cost_after: after, delta: after - before };
    });
    const round = (v, n) => Number(v.toFixed(n));
    return {
      basket: payload.name,
      cost_before: costBefore,
      cost_after: round(costAfter, 4),
      delta: round(costAfter - costBefore, 4),
      delta_pct: costBefore ? round((costAfter / costBefore - 1) * 100, 3) : null,
      components: components.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)),
      nota: "Inputs without a shock stay put. This computation does NOT propagate the move to "
        + "the others via correlation: that would turn an explicit scenario into a covert prediction.",
    };
  }

  return { routes, scenario };
}

// Answers one intercepted request. The dashboard's own code is untouched: the page
// installs a tiny classic script that defers every /api/ call here, which is what lets an
// async module stand in for a server that loads after the app's script has already run.
let api = null;
export function respond(data, url, init) {
  api ||= makeApi(data);
  const name = url.pathname.slice(5);
  const body = (init?.method === "POST" && name === "basket/scenario")
    ? api.scenario(JSON.parse(init.body))
    : api.routes[name]?.(url.searchParams);
  if (body === undefined) return new Response("not found", { status: 404 });
  return new Response(JSON.stringify(body), {
    status: 200, headers: { "content-type": "application/json" },
  });
}
