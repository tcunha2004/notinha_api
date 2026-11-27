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
            """SELECT id, name, brand, package_size::float8 AS package_size, package_unit
               FROM products ORDER BY lower(name), lower(brand) NULLS FIRST, package_size"""
        ).fetchall()
