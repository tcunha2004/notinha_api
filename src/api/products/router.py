import psycopg
from fastapi import APIRouter
from psycopg.rows import dict_row

from api.config.config import DATABASE_URL
from api.purchases.router import User

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(user_id: User):
    """Every product, for the edit sheet's picker. Products are shared by all users' items.
    The picker filters on the device, so this returns the whole catalog."""
    # ponytail: whole catalog per call; add `?q=` + LIMIT when it reaches tens of thousands.
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:  # type: ignore
        return conn.execute(
            """SELECT p.id, p.name, b.name AS brand, b.logo AS brand_logo,
                      p.package_size::float8 AS package_size, p.package_unit
               FROM products p LEFT JOIN brands b ON b.id = p.brand_id
               ORDER BY lower(p.name), lower(b.name) NULLS FIRST, p.package_size"""
        ).fetchall()
