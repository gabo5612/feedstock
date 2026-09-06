-- feedstock schema. Applied once, when the volume is initialised.
--
-- The split into layers is not cosmetic: `raw` is append-only and sacred, and everything
-- else is rebuilt from it. If a normalisation turns out to be wrong, it is corrected and
-- `core` is rebuilt without asking the source for anything again — a source that may well
-- have changed or disappeared.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS feat;
CREATE SCHEMA IF NOT EXISTS model;

-- ── RAW LAYER ─────────────────────────────────────────────────────────────
-- Never modified. The PK makes re-ingestion idempotent: running the ingester twice over
-- the same range does not duplicate a single row.
CREATE TABLE IF NOT EXISTS raw.ohlcv_ingest (
    source        text        NOT NULL,
    symbol        text        NOT NULL,
    interval      text        NOT NULL,
    ts            timestamptz NOT NULL,
    open          double precision,
    high          double precision,
    low           double precision,
    close         double precision,
    volume        double precision,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    payload_hash  text        NOT NULL,
    request_id    text,
    PRIMARY KEY (source, symbol, interval, ts)
);

SELECT create_hypertable('raw.ohlcv_ingest', 'ts', if_not_exists => TRUE);

-- ── INSTRUMENT REGISTRY ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS core.instrument (
    symbol                text PRIMARY KEY,
    source                text NOT NULL,
    source_ticker         text NOT NULL,
    -- Verified against the source's response, not against the bare ticker.
    -- ZN=F is NOT zinc: it is the 10-year Treasury note future. Putting it in a metals
    -- dataset would contaminate the whole model WITH NO VISIBLE ERROR. Hence the name the
    -- source returns is stored and compared.
    display_name_verified text NOT NULL,
    asset_class           text NOT NULL,
    unit                  text,
    currency              text,
    verified_at           timestamptz
);

-- ── NORMALISED LAYER ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS core.bar (
    symbol   text        NOT NULL REFERENCES core.instrument(symbol),
    interval text        NOT NULL,
    ts       timestamptz NOT NULL,
    open     double precision,
    high     double precision,
    low      double precision,
    close    double precision,
    volume   double precision,
    -- A flagged gap is a known gap. A silent gap gets interpolated by accident and ends
    -- up as an invented feature.
    is_gap   boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (symbol, interval, ts)
);

SELECT create_hypertable('core.bar', 'ts', if_not_exists => TRUE);

-- ── FEATURES ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feat.feature (
    symbol          text        NOT NULL,
    ts              timestamptz NOT NULL,
    name            text        NOT NULL,
    value           double precision,
    -- Two predictions are only comparable if they share feature_version. Without this, a
    -- change in a feature's definition turns a comparison into a coincidence.
    feature_version text        NOT NULL,
    PRIMARY KEY (symbol, ts, name, feature_version)
);

SELECT create_hypertable('feat.feature', 'ts', if_not_exists => TRUE);

-- ── MODELS ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model.run (
    run_id          bigserial PRIMARY KEY,
    model           text NOT NULL,
    params          jsonb NOT NULL DEFAULT '{}'::jsonb,
    feature_version text NOT NULL,
    train_window    tstzrange,
    git_sha         text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model.prediction (
    run_id    bigint      NOT NULL REFERENCES model.run(run_id) ON DELETE CASCADE,
    symbol    text        NOT NULL,
    -- origin_ts is the cut-off: the model that produced this row NEVER saw later data.
    -- The leakage guard in CI verifies exactly that, feature by feature.
    origin_ts timestamptz NOT NULL,
    horizon   int         NOT NULL,
    yhat      double precision,
    lo80      double precision,
    hi80      double precision,
    PRIMARY KEY (run_id, symbol, origin_ts, horizon)
);

CREATE TABLE IF NOT EXISTS model.metric (
    run_id  bigint NOT NULL REFERENCES model.run(run_id) ON DELETE CASCADE,
    symbol  text   NOT NULL,
    horizon int    NOT NULL,
    metric  text   NOT NULL,
    value   double precision,
    PRIMARY KEY (run_id, symbol, horizon, metric)
);
