# feedstock — static demo

The dashboard of the real project, served with no backend: the same UI, answering its own
API calls from an export of the real database.

## What runs here and what does not

| Component | In the demo | Why |
|---|---|---|
| Price series and the range selector | ✅ recomputed | Windowing over the exported bars |
| Statistics (min, max, average, annualised volatility) | ✅ recomputed | Ported from the SQL, `stddev_samp` over log returns |
| Correlation between instruments | ✅ recomputed | Pearson over returns, never over prices |
| Basket cost and exposure | ✅ replayed | Computed by the server at export time |
| Scenario ("copper +10%") | ✅ recomputed | Ported from `basket.escenario`, interactive |
| Signals, alerts, data-quality report | ✅ replayed | Computed by the server at export time |
| Ingester, TimescaleDB, alert evaluation | ❌ | They run inside the plant; that is the point of the project |

The exported dataset is the real one: 12 instruments, 30 302 daily bars, the verified
display names — including the trap the registry documents, `ZN=F` being a Treasury note
future rather than zinc.

## Verifying that the browser matches the backend

```bash
node verify.mjs      # 300/300 values agree with the Python backend
```

`data.json` carries reference answers computed by the server code. The script replays them
through the browser port and exits 1 on any disagreement, so a drift in the port fails
loudly instead of showing prettier numbers.

## A note on the window

The API asks for `now - days`. The demo anchors "now" to the export date rather than the
visitor's clock: a window that silently shrinks every day would make the page
irreproducible, and the reference answers would stop matching.

## Deploying

```bash
cd demo
vercel --prod
```

No environment variables, no database, no build step.

## Regenerating

```bash
docker-compose up -d
.venv/bin/python -m feedstock.export_demo
```

The exporter also rebuilds `index.html` from `src/feedstock/web/index.html`, so the demo
cannot drift from the app's own UI.
