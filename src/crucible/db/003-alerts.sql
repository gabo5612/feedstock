-- Alerts and their history.
CREATE TABLE IF NOT EXISTS core.alert_rule (
    id         bigserial PRIMARY KEY,
    name       text NOT NULL,
    symbol     text REFERENCES core.instrument(symbol),
    basket     text REFERENCES core.basket(name) ON DELETE CASCADE,
    kind       text NOT NULL,     -- price_above · price_below · z_above · z_below
                                  -- pos_below · pos_above · vol_above · basket_change_pct
    threshold  double precision NOT NULL,
    enabled    boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (symbol IS NOT NULL OR basket IS NOT NULL)
);

-- History: every time a rule CHANGES state. A row is not written per evaluation, only per
-- transition: a log repeating "still firing" every day stops being read within a week.
CREATE TABLE IF NOT EXISTS core.alert_event (
    id       bigserial PRIMARY KEY,
    rule_id  bigint NOT NULL REFERENCES core.alert_rule(id) ON DELETE CASCADE,
    ts       timestamptz NOT NULL DEFAULT now(),
    firing   boolean NOT NULL,
    value    double precision,
    mensaje  text
);
CREATE INDEX IF NOT EXISTS alert_event_rule_ts ON core.alert_event (rule_id, ts DESC);
