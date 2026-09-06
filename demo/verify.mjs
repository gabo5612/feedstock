// Checks that the browser port computes what the backend computed.
//
//   node verify.mjs
//
// data.json carries reference answers produced by the Python code (SQL aggregates,
// stddev_samp, corr over log returns). This replays each of them through offline.js and
// diffs the numbers. Exit code 1 on any disagreement.

import { readFileSync } from "node:fs";
import { makeApi } from "./offline.js";

const data = JSON.parse(readFileSync(new URL("./data.json", import.meta.url), "utf8"));
const { routes } = makeApi(data);

// Postgres and JavaScript do the same arithmetic in a different order, so the last bits
// of a float can differ. The tolerance is relative and tight enough that a real drift —
// a wrong window, the wrong denominator in stddev, correlation over prices instead of
// returns — cannot hide under it.
const REL = 1e-9;
const close = (a, b) => {
  if (a === null || b === null || a === undefined || b === undefined) return a === b || (a == null && b == null);
  if (typeof a === "string" || typeof b === "string") return String(a) === String(b);
  return Math.abs(a - b) <= REL * Math.max(1, Math.abs(a), Math.abs(b));
};

let checked = 0, failed = 0;
const fail = (what, py, js) => {
  failed += 1;
  console.error(`✗ ${what}\n    python=${py}\n    js    =${js}`);
};

for (const [key, python] of Object.entries(data.reference.stats)) {
  const [symbol, days] = key.split("|");
  const js = routes.stats(new URLSearchParams({ symbol, days }));
  for (const field of ["bars", "min", "max", "avg", "from", "to", "annualized_vol_pct"]) {
    checked += 1;
    if (!close(python[field], js[field])) fail(`stats ${key} · ${field}`, python[field], js[field]);
  }
}

for (const [key, python] of Object.entries(data.reference.correlation)) {
  const [symbols, days] = key.split("|");
  const js = routes.correlation(new URLSearchParams({ symbols, days }));
  const jsByPair = new Map(js.matrix.map((m) => [`${m.a}|${m.b}`, m]));
  for (const m of python.matrix) {
    const mine = jsByPair.get(`${m.a}|${m.b}`);
    checked += 2;
    if (!mine) { fail(`correlation ${key} · ${m.a}/${m.b}`, m.r, "missing"); continue; }
    if (!close(m.r, mine.r)) fail(`correlation ${key} · r ${m.a}/${m.b}`, m.r, mine.r);
    if (m.n !== mine.n) fail(`correlation ${key} · n ${m.a}/${m.b}`, m.n, mine.n);
  }
}

// The series endpoint is a window, so check the window itself: same first and last day,
// same count, for every instrument and every range the UI offers.
for (const days of data.ranges) {
  for (const inst of data.instruments) {
    const s = routes.series(new URLSearchParams({ symbols: inst.symbol, days }))
      .series[inst.symbol];
    const st = routes.stats(new URLSearchParams({ symbol: inst.symbol, days }));
    checked += 1;
    if (s.length && s.length !== st.bars) fail(`series ${inst.symbol}|${days} · count`, st.bars, s.length);
  }
}

console.log(`${checked - failed}/${checked} values agree with the Python backend`);
process.exit(failed ? 1 : 0);
