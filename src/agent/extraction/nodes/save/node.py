import mimetypes
from uuid import UUID

import boto3
import psycopg
from agent.extraction.nodes.extract.models import Item
from agent.extraction.state import GraphState
from api.config.config import AWS_REGION, DATABASE_URL, S3_BUCKET_NAME

s3 = boto3.client("s3", region_name=AWS_REGION)


class DuplicatePurchase(Exception):
    """The user already saved a purchase from this store at this exact date and time."""

    def __init__(self, purchase_id: UUID):
        super().__init__("This invoice was already saved")
        self.purchase_id = purchase_id


def s3_key(user_id: str, purchase_id: UUID, media_type: str) -> str:
    """Where the invoice image lives inside the bucket (S3_BUCKET_NAME in .env)."""
    extension = mimetypes.guess_extension(media_type) or ""
    return f"{user_id}/{purchase_id}{extension}"


def find_or_create_product(
    conn: psycopg.Connection, store_id: UUID | None, item: Item
) -> UUID | None:
    """The product of this item line, or None when it can't be identified."""
    # 1. Same store + same code: the store's own catalog code, so it's surely the same product
    #    (even if the LLM named it differently this time).
    if store_id and item.code:
        row = conn.execute(
            """SELECT pi.product_id FROM purchase_items pi
               JOIN purchases p ON p.id = pi.purchase_id
               WHERE p.store_id = %s AND pi.code = %s AND pi.product_id IS NOT NULL
               LIMIT 1""",
            (store_id, item.code),
        ).fetchone()
        if row:
            return row[0]

    # 2. Same name + brand (ignoring case) + size + unit, in any store; or a new product.
    p = item.product
    if not (p and p.name):
        return None
    # The ON CONFLICT columns must match products_identity_idx (schema.sql) exactly.
    # DO UPDATE (a no-op that keeps the saved casing) instead of DO NOTHING,
    # so RETURNING also gives the id of an existing row.
    row = conn.execute(
        """INSERT INTO products (name, brand, package_size, package_unit) VALUES (%s, %s, %s, %s)
           ON CONFLICT (lower(name), lower(brand), package_size, package_unit)
           DO UPDATE SET name = products.name
           RETURNING id""",
        (p.name, p.brand, p.package_size, p.package_unit),
    ).fetchone()
    return row[0]  # type: ignore[index]


def node_save(state: GraphState) -> dict:
    data = state["data"]  # type: ignore[typeddict-item]
    store, purchase = data.store, data.purchase
    purchase_id = state["uuid"]
    key = s3_key(state["user_id"], purchase_id, state["media_type"])

    # One transaction: commits at the end of the block, rolls back on any exception.
    with psycopg.connect(DATABASE_URL) as conn:
        # Duplicate error if the same receipt
        if store and store.id and purchase and purchase.purchased_at:
            existing = conn.execute(
                """SELECT p.id FROM purchases p JOIN stores s ON s.id = p.store_id
                   WHERE p.user_id = %s AND s.cnpj = %s AND p.purchased_at = %s
                   LIMIT 1""",
                (state["user_id"], store.id, purchase.purchased_at),
            ).fetchone()
            if existing:
                raise DuplicatePurchase(existing[0])

        store_id = None
        if store and store.id:  # no CNPJ = can't identify the store, leave it null
            row = conn.execute(
                """INSERT INTO stores (cnpj, name, address, logo) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (cnpj) DO UPDATE SET
                       name = COALESCE(EXCLUDED.name, stores.name),
                       address = COALESCE(EXCLUDED.address, stores.address),
                       logo = COALESCE(EXCLUDED.logo, stores.logo)
                   RETURNING id""",
                (store.id, store.name, store.address, state.get("store_logo")),
            ).fetchone()
            store_id = row[0]  # type: ignore[index]

        conn.execute(
            """INSERT INTO purchases (id, user_id, store_id, purchased_at, total_amount,
                                      payment_method, s3_object_key, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                purchase_id,
                state["user_id"],
                store_id,
                purchase and purchase.purchased_at,
                purchase and purchase.total_amount,
                purchase and purchase.payment_method,
                key,
                state["save_status"],  # type: ignore[typeddict-item]
            ),
        )
        # One by one (not executemany): each line can find the product of the lines saved before it.
        for i in data.items:
            conn.execute(
                """INSERT INTO purchase_items (purchase_id, raw_description, code, quantity,
                                               unit, unit_price, discount, total_amount, product_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    purchase_id,
                    i.raw_description,
                    i.code,
                    i.quantity,
                    i.unit,
                    i.unit_price,
                    i.discount,
                    i.total_amount,
                    find_or_create_product(conn, store_id, i),
                ),
            )

        # Upload last, still inside the transaction: if S3 fails, the rows above roll back.
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=state["image"],
            ContentType=state["media_type"],
        )
    return {}
