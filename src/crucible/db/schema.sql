-- Esquema de crucible. Se aplica una sola vez, al inicializar el volumen.
--
-- La division en capas no es cosmetica: `raw` es append-only y sagrada, y todo lo demas
-- se reconstruye desde ahi. Si una normalizacion resulta estar mal, se corrige y se
-- reconstruye `core` sin volver a pedirle nada a la fuente — que ademas puede haber
-- cambiado o desaparecido.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS feat;
CREATE SCHEMA IF NOT EXISTS model;

-- ── CAPA CRUDA ────────────────────────────────────────────────────────────
-- Nunca se modifica. La PK hace la reingesta idempotente: correr el ingester dos veces
-- sobre el mismo tramo no duplica una sola fila.
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

-- ── REGISTRO DE INSTRUMENTOS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS core.instrument (
    symbol                text PRIMARY KEY,
    source                text NOT NULL,
    source_ticker         text NOT NULL,
    -- Verificado contra la respuesta de la fuente, no contra el ticker a secas.
    -- ZN=F NO es zinc: es el futuro del bono del Tesoro a 10 anos. Meterlo en un dataset
    -- de metales contaminaria el modelo entero SIN ERROR VISIBLE. Por eso el nombre que
    -- devuelve la fuente se guarda y se compara.
    display_name_verified text NOT NULL,
    asset_class           text NOT NULL,
    unit                  text,
    currency              text,
    verified_at           timestamptz
);

-- ── CAPA NORMALIZADA ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS core.bar (
    symbol   text        NOT NULL REFERENCES core.instrument(symbol),
    interval text        NOT NULL,
    ts       timestamptz NOT NULL,
    open     double precision,
    high     double precision,
    low      double precision,
    close    double precision,
    volume   double precision,
    -- Un hueco marcado es un hueco conocido. Un hueco silencioso se interpola sin querer
    -- y termina siendo una feature inventada.
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
    -- Dos predicciones solo son comparables si comparten feature_version. Sin esto, un
    -- cambio de definicion de feature convierte una comparacion en una coincidencia.
    feature_version text        NOT NULL,
    PRIMARY KEY (symbol, ts, name, feature_version)
);

SELECT create_hypertable('feat.feature', 'ts', if_not_exists => TRUE);

-- ── MODELOS ───────────────────────────────────────────────────────────────
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
    -- origin_ts es el corte: el modelo que produjo esta fila NUNCA vio datos posteriores.
    -- El guard de fuga en CI verifica exactamente eso, feature por feature.
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
