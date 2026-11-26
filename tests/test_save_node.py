"""Postgres-backed tests: the save node and the login's user upsert (real SQL)."""

from datetime import datetime
from uuid import uuid4

import psycopg
import pytest

from agent.extraction.nodes.extract.models import (
    ExtractionOutput,
    Item,
    Product,
    Purchase,
    Store,
    format_cnpj,
)
from agent.extraction.nodes.save import node as save_node
from agent.extraction.state import GraphState, MediaType, SaveStatus
from api.auth import load_user, upsert_user  # bound before conftest's in-memory patch
from api.config.config import DATABASE_URL

try:
    psycopg.connect(DATABASE_URL, connect_timeout=2).close()
except psycopg.OperationalError:
    pytest.skip(
        "Postgres not running (docker compose up -d postgres)", allow_module_level=True
    )

def random_cnpj() -> str:
    """A fresh valid CNPJ per run: exactly one of the 100 possible check-digit suffixes passes."""
    base = f"{uuid4().int % 10**12:012}"
    return next(c for i in range(100) if format_cnpj(c := f"{base}{i:02}"))


DATA = ExtractionOutput(
    store=Store(name="Mercado", id=random_cnpj(), address="Rua A"),
    purchase=Purchase(
        total_amount=12.9,
        payment_method="PIX",
        purchased_at=datetime(2025, 3, 15, 14, 32),
    ),
    items=[
        Item(
            raw_description="ARROZ",
            quantity=2,
            unit="UN",
            unit_price=3.5,
            total_amount=7,
        ),
        Item(raw_description="BANANA", quantity=0.535, unit="KG", total_amount=5.9),
    ],
)


class FakeS3:
    def __init__(self, fail=False):
        self.fail, self.keys = fail, []

    def put_object(self, **kw):
        if self.fail:
            raise RuntimeError("S3 down")
        self.keys.append(kw["Key"])


def new_user():
    sub = f"sub-{uuid4()}"
    return upsert_user(
        {"sub": sub, "email": f"{sub}@test.com", "name": "Ana", "picture": "p.png"}
    )


def state(user_id, status=SaveStatus.OK) -> GraphState:
    return {
        "uuid": uuid4(),
        "user_id": user_id,
        "image": b"img",
        "media_type": MediaType.JPG,
        "data": DATA,
        "save_status": status,
    }


def row(sql, *args):
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(sql, args).fetchone()


def test_upsert_user_creates_once_and_refreshes_profile():
    claims = {
        "sub": f"sub-{uuid4()}",
        "email": "a@test.com",
        "name": "Ana",
        "picture": "p.png",
    }
    user_id = upsert_user(claims)
    again = upsert_user({**claims, "email": "new@test.com", "name": "Ana S."})
    assert again == user_id  # same Google account = same user, even with a new email
    assert load_user(user_id) == {
        "email": "new@test.com",
        "name": "Ana S.",
        "picture": "p.png",
    }


def test_saves_purchase_items_and_image(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(save_node, "s3", s3)
    user_id = new_user()
    s = state(user_id)
    s["store_logo"] = "https://x.com/logo.png"
    save_node.node_save(s)

    store_id, total, status, key = row(  # type: ignore
        "SELECT store_id, total_amount, status, s3_object_key FROM purchases WHERE id = %s",
        s["uuid"],
    )
    assert (str(total), status) == ("12.9", "ok")
    assert s3.keys == [key] == [f"{user_id}/{s['uuid']}.jpg"]
    assert row(
        "SELECT count(*) FROM purchase_items WHERE purchase_id = %s", s["uuid"]
    ) == (2,)

    # Same store, another time: store reused, not duplicated.
    later = DATA.model_copy(
        update={
            "purchase": DATA.purchase.model_copy(  # type: ignore[union-attr]
                update={"purchased_at": datetime(2025, 3, 15, 18, 0)}
            )
        }
    )
    s2 = state(user_id, SaveStatus.REVIEW)
    s2["data"] = later
    save_node.node_save(s2)
    assert row("SELECT store_id, status FROM purchases WHERE id = %s", s2["uuid"]) == (
        store_id,
        "needs_review",
    )
    # No logo on the second save (already known): the saved one is kept.
    assert row("SELECT logo FROM stores WHERE id = %s", store_id) == (
        "https://x.com/logo.png",
    )


def test_same_store_date_and_time_is_refused_before_any_insert(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(save_node, "s3", s3)
    user_id = new_user()
    first = state(user_id)
    save_node.node_save(first)

    again = state(user_id)
    with pytest.raises(save_node.DuplicatePurchase) as e:
        save_node.node_save(again)
    assert e.value.purchase_id == first["uuid"]
    assert row("SELECT count(*) FROM purchases WHERE id = %s", again["uuid"]) == (0,)
    assert len(s3.keys) == 1  # the second photo never reached S3

    # Another user with the same receipt is not a duplicate.
    save_node.node_save(state(new_user()))


def test_links_items_to_products(monkeypatch):
    monkeypatch.setattr(save_node, "s3", FakeS3())
    user_id = new_user()
    name = f"Arroz {uuid4()}"  # unique per run: the products table outlives the tests
    store_a, store_b = random_cnpj(), random_cnpj()

    def save(cnpj, hour, product_name, code, brand="Tio João"):
        s = state(user_id)
        s["data"] = DATA.model_copy(
            update={
                "store": Store(name="Mercado", id=cnpj),
                "purchase": Purchase(purchased_at=datetime(2025, 3, 15, hour)),
                "items": [
                    Item(
                        raw_description="ARROZ TIO JOAO 5KG",
                        code=code,
                        product=Product(
                            name=product_name,
                            brand=brand,
                            package_size=5000,
                            package_unit="g",
                        ),
                    ),
                    Item(raw_description="XPTO", code="999"),  # LLM couldn't interpret it
                ],
            }
        )
        save_node.node_save(s)
        with psycopg.connect(DATABASE_URL) as conn:
            return [
                r[0]
                for r in conn.execute(
                    "SELECT product_id FROM purchase_items WHERE purchase_id = %s ORDER BY position",
                    (s["uuid"],),
                )
            ]

    product_id, no_product = save(store_a, 10, name, code="001")
    assert product_id is not None and no_product is None

    # Same store + code wins, even with a different name from the LLM.
    assert save(store_a, 11, f"{name} branco", code="001") == [product_id, None]
    # Another store, unknown code: found by name + brand + size + unit.
    assert save(store_b, 12, name, code="777") == [product_id, None]
    # Casing doesn't matter, and the first saved casing is kept.
    assert save(store_b, 13, name.upper(), code="888", brand="TIO JOÃO") == [product_id, None]

    assert row("SELECT count(*) FROM products WHERE name ILIKE %s", f"{name}%") == (1,)
    assert row("SELECT name, brand FROM products WHERE id = %s", product_id) == (name, "Tio João")


def test_s3_failure_rolls_back_db(monkeypatch):
    monkeypatch.setattr(save_node, "s3", FakeS3(fail=True))
    s = state(new_user())
    with pytest.raises(RuntimeError):
        save_node.node_save(s)
    assert row("SELECT count(*) FROM purchases WHERE id = %s", s["uuid"]) == (0,)
