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
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Nullable columns: a "needs_review" purchase may come from a partial extraction.
CREATE TABLE purchases (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users (id),
    store_id       uuid REFERENCES stores (id),
    purchased_at   timestamp,  -- local time as printed on the receipt, no timezone
    total_amount   numeric,
    payment_method text,
    s3_object_key  text NOT NULL,
    status         text NOT NULL CHECK (status IN ('ok', 'needs_review')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON purchases (user_id);
CREATE INDEX ON purchases (store_id);

CREATE TABLE purchase_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    purchase_id     uuid NOT NULL REFERENCES purchases (id) ON DELETE CASCADE,
    position        bigserial,  -- insertion order = order printed on the receipt
    raw_description text,       -- NULL for items the user added by hand
    description     text,       -- the user's friendly name ("Pão francês")
    code            text,
    quantity        numeric,
    unit            text,  -- UN, KG, L, ... (as printed)
    unit_price      numeric,
    discount        numeric NOT NULL DEFAULT 0,
    total_amount    numeric
);
CREATE INDEX ON purchase_items (purchase_id);
