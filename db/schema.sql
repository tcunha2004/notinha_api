-- Runs automatically ONLY on the first start of the Postgres container (empty volume).
-- After changing this file: `docker compose down -v && docker compose up -d` (wipes the data).

CREATE TABLE users (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    google_sub text NOT NULL UNIQUE,  -- Google's permanent user ID (the email can change)
    email      text NOT NULL,
    name       text NOT NULL,
    picture    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE stores (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cnpj       text NOT NULL UNIQUE,
    name       text,
    address    text,
    logo       text,  -- image URL found on the web (store_logo node); NULL = not found
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Same values as PaymentMethod in src/agent/extraction/nodes/extract/models.py
CREATE TYPE payment_method AS ENUM ('DÉBITO', 'CRÉDITO', 'PIX', 'DINHEIRO');

-- Nullable columns: a "needs_review" purchase may come from a partial extraction.
CREATE TABLE purchases (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users (id),
    store_id       uuid REFERENCES stores (id),
    purchased_at   timestamp,  -- local time as printed on the receipt, no timezone
    total_amount   numeric,
    payment_method payment_method,  -- NULL = not read, or another method
    s3_object_key  text NOT NULL,
    status         text NOT NULL CHECK (status IN ('ok', 'needs_review')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON purchases (user_id);
CREATE INDEX ON purchases (store_id);

-- Standardized product, the same across stores (interpreted by the LLM from raw_description).
CREATE TABLE products (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,  -- casing of the first time it was saved
    brand        text,
    package_size numeric,  -- in package_unit; NULL for items sold by weight/volume
    package_unit text CHECK (package_unit IN ('g', 'ml', 'un')),
    created_at   timestamptz NOT NULL DEFAULT now()
);
-- Product identity. lower(): "Café" and "café" are the same product.
-- NULLS NOT DISTINCT: two "Banana prata" with brand NULL are the same product, not two.
CREATE UNIQUE INDEX products_identity_idx
    ON products (lower(name), lower(brand), package_size, package_unit) NULLS NOT DISTINCT;

CREATE TABLE purchase_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    purchase_id     uuid NOT NULL REFERENCES purchases (id) ON DELETE CASCADE,
    position        bigserial,  -- insertion order = order printed on the receipt
    raw_description text,       -- as printed; NULL for items the user added by hand
    code            text,
    quantity        numeric,
    unit            text,  -- UN, KG, L, ... (as printed)
    unit_price      numeric,
    discount        numeric NOT NULL DEFAULT 0,
    total_amount    numeric,
    product_id      uuid REFERENCES products (id)  -- its name is the item's name; NULL = not identified
);
CREATE INDEX ON purchase_items (purchase_id);
CREATE INDEX ON purchase_items (product_id);
CREATE INDEX ON purchase_items (code);  -- store + code lookup in the save node
