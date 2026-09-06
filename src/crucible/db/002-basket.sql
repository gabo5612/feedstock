-- Canasta de costo: la mezcla real de insumos de un producto.
--
-- Es lo que convierte esto de "precios de commodities" a "el costo de ESTA planta".

CREATE TABLE IF NOT EXISTS core.basket (
    name        text PRIMARY KEY,
    description text,
    output_unit text NOT NULL DEFAULT 'tonelada de producto',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.basket_item (
    basket   text NOT NULL REFERENCES core.basket(name) ON DELETE CASCADE,
    symbol   text NOT NULL REFERENCES core.instrument(symbol),
    -- Cantidad por unidad de producto, EN LA UNIDAD DE ABAJO.
    qty      double precision NOT NULL CHECK (qty > 0),
    -- La unidad en que el usuario piensa (kg, MWh...). La conversion a la unidad en que
    -- cotiza el instrumento (USD/lb, USD/MMBtu) es explicita y esta en units.py: una
    -- conversion implicita 1:1 entre kg y lb daria un costo 2.2 veces mal SIN ERROR.
    qty_unit text NOT NULL,
    nota     text,
    PRIMARY KEY (basket, symbol)
);
