-- Cost basket: a product's real input mix.
--
-- This is what turns the project from "commodity prices" into "THIS plant's cost".

CREATE TABLE IF NOT EXISTS core.basket (
    name        text PRIMARY KEY,
    description text,
    output_unit text NOT NULL DEFAULT 'tonelada de producto',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.basket_item (
    basket   text NOT NULL REFERENCES core.basket(name) ON DELETE CASCADE,
    symbol   text NOT NULL REFERENCES core.instrument(symbol),
    -- Quantity per unit of product, IN THE UNIT BELOW.
    qty      double precision NOT NULL CHECK (qty > 0),
    -- The unit the user thinks in (kg, MWh...). Conversion to the unit the instrument
    -- trades in (USD/lb, USD/MMBtu) is explicit and lives in units.py: an implicit 1:1
    -- conversion between kg and lb would give a cost 2.2x wrong WITH NO ERROR.
    qty_unit text NOT NULL,
    nota     text,
    PRIMARY KEY (basket, symbol)
);
