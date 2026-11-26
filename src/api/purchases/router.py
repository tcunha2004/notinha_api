from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from psycopg.rows import dict_row

from agent.extraction.nodes.save.node import s3, upsert_product
from api.auth import current_user_id
from api.config.config import DATABASE_URL, S3_BUCKET_NAME
from api.purchases.schemas import ItemIn, PurchaseIn

router = APIRouter(prefix="/purchases", tags=["purchases"])

User = Annotated[str, Depends(current_user_id)]

# A line "needs a look" when something wasn't read or its math doesn't close.
# The printed total may be gross or net of the discount, so either one counts as matching.
_FLAGGED = """(i.quantity IS NULL OR i.unit_price IS NULL OR i.total_amount IS NULL
    OR (abs(i.quantity * i.unit_price - i.total_amount) >= 0.01
        AND abs(i.quantity * i.unit_price - i.discount - i.total_amount) >= 0.01))"""

# Numbers come back as float8 so they reach the frontend as JSON numbers, not strings.
_ITEMS_SQL = f"""
    SELECT i.id, i.purchase_id, i.position, i.raw_description, i.code,
           COALESCE(i.quantity, 0)::float8 AS quantity, COALESCE(i.unit, 'UN') AS unit,
           COALESCE(i.unit_price, 0)::float8 AS unit_price, i.discount::float8 AS discount,
           COALESCE(i.total_amount, 0)::float8 AS total_amount, {_FLAGGED} AS flagged,
           pr.id AS product_id, pr.name AS product_name, pr.brand AS product_brand,
           pr.package_size::float8 AS product_package_size, pr.package_unit AS product_package_unit
    FROM purchase_items i JOIN purchases p ON p.id = i.purchase_id
    LEFT JOIN products pr ON pr.id = i.product_id
    WHERE p.user_id = %s AND (%s::uuid IS NULL OR p.id = %s)
    ORDER BY i.position"""

# Unreadable date: fall back to the upload time. Unreadable total: 0, so the "Diferença" row shows it.
_PURCHASES_SQL = """
    SELECT p.id, p.status, p.payment_method,
           COALESCE(p.purchased_at, p.created_at AT TIME ZONE 'America/Sao_Paulo') AS purchased_at,
           COALESCE(p.total_amount, 0)::float8 AS total_amount,
           s.cnpj, s.name AS store_name, s.address, s.logo
    FROM purchases p LEFT JOIN stores s ON s.id = p.store_id
    WHERE p.user_id = %s AND (%s::uuid IS NULL OR p.id = %s)
    ORDER BY purchased_at DESC"""

# Re-checked after every item change: ok only when every line has a total and they add up to the receipt.
_REFRESH_STATUS_SQL = """
    UPDATE purchases p SET status = CASE
        WHEN p.total_amount IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM purchase_items WHERE purchase_id = p.id AND total_amount IS NULL)
         AND abs(p.total_amount - (SELECT COALESCE(sum(total_amount), 0)
                                   FROM purchase_items WHERE purchase_id = p.id)) < 0.005
        THEN 'ok' ELSE 'needs_review' END
    WHERE p.id = %s"""


_PRODUCT_FIELDS = ("id", "name", "brand", "package_size", "package_unit")


def load_purchases(user_id: str, purchase_id: UUID | None = None) -> list[dict]:
    """The user's purchases (newest first) with store and items, shaped like the frontend's Purchase."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:  # type: ignore
        args = (user_id, purchase_id, purchase_id)
        rows = conn.execute(_PURCHASES_SQL, args).fetchall()
        items = conn.execute(_ITEMS_SQL, args).fetchall()

    by_purchase: dict[UUID, list[dict]] = {}
    for item in items:
        product = {k: item.pop(f"product_{k}") for k in _PRODUCT_FIELDS}  # type: ignore
        item["product"] = product if product["id"] else None  # type: ignore
        by_purchase.setdefault(item["purchase_id"], []).append(item)  # type: ignore

    purchases = []
    for row in rows:
        cnpj, name, address, logo = (row.pop(k) for k in ("cnpj", "store_name", "address", "logo"))  # type: ignore
        row["store"] = (  # type: ignore
            {"cnpj": cnpj, "name": name, "address": address, "logo": logo}
            if cnpj
            else None
        )
        row["items"] = by_purchase.get(row["id"], [])  # type: ignore
        purchases.append(row)
    return purchases


def _get_one(user_id: str, purchase_id: UUID) -> dict:
    found = load_purchases(user_id, purchase_id)
    if not found:
        raise HTTPException(status_code=404, detail="Purchase not found")
    return found[0]


@router.get("")
def list_purchases(user_id: User):
    return load_purchases(user_id)


@router.get("/{purchase_id}")
def get_purchase(purchase_id: UUID, user_id: User):
    return _get_one(user_id, purchase_id)


@router.get("/{purchase_id}/photo")
def get_photo(purchase_id: UUID, user_id: User):
    """Redirects to a short-lived S3 link, so the bucket stays private."""
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT s3_object_key FROM purchases WHERE id = %s AND user_id = %s",
            (purchase_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Purchase not found")
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": S3_BUCKET_NAME, "Key": row[0]}, ExpiresIn=300
    )
    return RedirectResponse(url)



@router.patch("/{purchase_id}")
def update_purchase(purchase_id: UUID, body: PurchaseIn, user_id: User):
    """Saves the corrected total and re-checks it against the items. Returns the updated purchase."""
    with psycopg.connect(DATABASE_URL) as conn:
        updated = conn.execute(
            "UPDATE purchases SET total_amount = %s WHERE id = %s AND user_id = %s",
            (round(body.total_amount, 2), purchase_id, user_id),
        ).rowcount
        if not updated:
            raise HTTPException(status_code=404, detail="Purchase not found")
        conn.execute(_REFRESH_STATUS_SQL, (purchase_id,))
    return _get_one(user_id, purchase_id)


@router.patch("/{purchase_id}/items/{item_id}")
def update_item(purchase_id: UUID, item_id: UUID, body: ItemIn, user_id: User):
    """Saves the correction and re-checks the purchase total. Returns the updated purchase.
    The name links the item to the product with that name, keeping the brand and size it had."""
    with psycopg.connect(DATABASE_URL) as conn:
        current = conn.execute(
            """SELECT i.raw_description, i.product_id, pr.brand, pr.package_size, pr.package_unit
               FROM purchase_items i JOIN purchases p ON p.id = i.purchase_id
               LEFT JOIN products pr ON pr.id = i.product_id
               WHERE i.id = %s AND p.id = %s AND p.user_id = %s""",
            (item_id, purchase_id, user_id),
        ).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Item not found")
        raw_description, product_id, *brand_and_size = current
        # The form always sends a name. An unidentified item whose name is still the
        # receipt text (only numbers were fixed) stays without a product.
        if product_id or body.name != raw_description:
            product_id = upsert_product(conn, body.name, *brand_and_size)
        conn.execute(
            """UPDATE purchase_items
               SET product_id = %s, quantity = %s, unit = %s, unit_price = %s,
                   discount = %s, total_amount = %s
               WHERE id = %s""",
            (product_id, *body.values(), item_id),
        )
        conn.execute(_REFRESH_STATUS_SQL, (purchase_id,))
    return _get_one(user_id, purchase_id)


@router.post("/{purchase_id}/items", status_code=201)
def add_item(purchase_id: UUID, body: ItemIn, user_id: User):
    """For a line the reading missed (no raw_description). Returns the updated purchase."""
    with psycopg.connect(DATABASE_URL) as conn:
        inserted = conn.execute(
            """INSERT INTO purchase_items
                   (purchase_id, product_id, quantity, unit, unit_price, discount, total_amount)
               SELECT id, %s, %s, %s, %s, %s, %s FROM purchases WHERE id = %s AND user_id = %s""",
            (upsert_product(conn, body.name, None, None, None), *body.values(), purchase_id, user_id),
        ).rowcount
        if not inserted:  # the 404 rolls back the product created above
            raise HTTPException(status_code=404, detail="Purchase not found")
        conn.execute(_REFRESH_STATUS_SQL, (purchase_id,))
    return _get_one(user_id, purchase_id)


@router.delete("/{purchase_id}/items/{item_id}")
def delete_item(purchase_id: UUID, item_id: UUID, user_id: User):
    """Removes a line (e.g. read twice) and re-checks the total. Returns the updated purchase."""
    with psycopg.connect(DATABASE_URL) as conn:
        deleted = conn.execute(
            """DELETE FROM purchase_items i USING purchases p
               WHERE i.id = %s AND i.purchase_id = p.id AND p.id = %s AND p.user_id = %s""",
            (item_id, purchase_id, user_id),
        ).rowcount
        if not deleted:
            raise HTTPException(status_code=404, detail="Item not found")
        conn.execute(_REFRESH_STATUS_SQL, (purchase_id,))
    return _get_one(user_id, purchase_id)


@router.delete("/{purchase_id}", status_code=204)
def delete_purchase(purchase_id: UUID, user_id: User):
    """Deletes the purchase, its items (ON DELETE CASCADE) and the receipt photo."""
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "DELETE FROM purchases WHERE id = %s AND user_id = %s RETURNING s3_object_key",
            (purchase_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Purchase not found")
        # Still inside the transaction: if S3 fails, the rows come back and the user can retry.
        s3.delete_object(Bucket=S3_BUCKET_NAME, Key=row[0])
    return Response(status_code=204)
