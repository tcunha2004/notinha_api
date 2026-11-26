"""Postgres-backed tests: the save node and the login's user upsert (real SQL)."""

from datetime import datetime
from uuid import uuid4

import psycopg
import pytest

from agent.extraction.nodes.extract.models import (
    ExtractionOutput,
    Item,
    Purchase,
    Store,
)
from agent.extraction.nodes.save import node as save_node
from agent.extraction.state import MediaType, SaveStatus
from api.auth import load_user, upsert_user  # bound before conftest's in-memory patch
from api.config.config import DATABASE_URL

try:
    psycopg.connect(DATABASE_URL, connect_timeout=2).close()
except psycopg.OperationalError:
    pytest.skip("Postgres not running (docker compose up -d postgres)", allow_module_level=True)

DATA = ExtractionOutput(
    store=Store(name="Mercado", id=f"cnpj-{uuid4()}", address="Rua A"),
    purchase=Purchase(total_amount=12.9, payment_method="PIX", purchased_at=datetime(2025, 3, 15, 14, 32)),
    items=[Item(raw_description="ARROZ", quantity=2, unit="UN", unit_price=3.5, total_amount=7),
           Item(raw_description="BANANA", quantity=0.535, unit="KG", total_amount=5.9)],
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
    return upsert_user({"sub": sub, "email": f"{sub}@test.com", "name": "Ana", "picture": "p.png"})


def state(user_id, status=SaveStatus.OK):
    return {"uuid": uuid4(), "user_id": user_id, "image": b"img",
            "media_type": MediaType.JPG, "data": DATA, "save_status": status}


def row(sql, *args):
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(sql, args).fetchone()


def test_upsert_user_creates_once_and_refreshes_profile():
    claims = {"sub": f"sub-{uuid4()}", "email": "a@test.com", "name": "Ana", "picture": "p.png"}
    user_id = upsert_user(claims)
    again = upsert_user({**claims, "email": "new@test.com", "name": "Ana S."})
    assert again == user_id  # same Google account = same user, even with a new email
    assert load_user(user_id) == {"email": "new@test.com", "name": "Ana S.", "picture": "p.png"}


def test_saves_purchase_items_and_image(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(save_node, "s3", s3)
    user_id = new_user()
    s = state(user_id)
    save_node.node_save(s)

    store_id, total, status, key = row(
        "SELECT store_id, total_amount, status, s3_object_key FROM purchases WHERE id = %s", s["uuid"])
    assert (str(total), status) == ("12.9", "ok")
    assert s3.keys == [key] == [f"{user_id}/{s['uuid']}.jpg"]
    assert row("SELECT count(*) FROM purchase_items WHERE purchase_id = %s", s["uuid"]) == (2,)

    # Same store, another time: store reused, not duplicated.
    later = DATA.model_copy(update={"purchase": DATA.purchase.model_copy(  # type: ignore[union-attr]
        update={"purchased_at": datetime(2025, 3, 15, 18, 0)})})
    s2 = {**state(user_id, SaveStatus.REVIEW), "data": later}
    save_node.node_save(s2)
    assert row("SELECT store_id, status FROM purchases WHERE id = %s", s2["uuid"]) == (
        store_id, "needs_review")


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


def test_s3_failure_rolls_back_db(monkeypatch):
    monkeypatch.setattr(save_node, "s3", FakeS3(fail=True))
    s = state(new_user())
    with pytest.raises(RuntimeError):
        save_node.node_save(s)
    assert row("SELECT count(*) FROM purchases WHERE id = %s", s["uuid"]) == (0,)
