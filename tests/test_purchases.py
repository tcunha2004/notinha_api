"""Purchase routes against the real Postgres: reading, ownership, item edits and the status re-check."""

from datetime import datetime
from uuid import uuid4

import psycopg
import pytest
from test_save_node import (  # importing it also skips this file when Postgres is down
    DATA,
    FakeS3,
    state,
)

from agent.extraction.nodes.extract.models import Purchase
from agent.extraction.nodes.save import node as save_node
from api.purchases import router as purchases_api
from api.auth import upsert_user  # bound before conftest's in-memory patch
from api.config.config import DATABASE_URL


class FakeS3WithDelete(FakeS3):
    def __init__(self, fail_delete=False):
        super().__init__()
        self.fail_delete, self.deleted = fail_delete, []

    def delete_object(self, **kw):
        if self.fail_delete:
            raise RuntimeError("S3 down")
        self.deleted.append(kw["Key"])


@pytest.fixture
def saved(client, redis_client, monkeypatch):
    """A purchase saved by the real save node (total 12.90, items 7.00 + 5.90), plus a logged-in client."""
    monkeypatch.setattr(save_node, "s3", FakeS3WithDelete())
    sub = f"sub-{uuid4()}"
    user_id = upsert_user(
        {"sub": sub, "email": f"{sub}@t.com", "name": "Ana", "picture": ""}
    )
    s = state(user_id)
    save_node.node_save(s)
    redis_client.set("session:abc", user_id)
    client.cookies.set("session", "abc")
    return client, str(s["uuid"])


def test_get_purchase_with_store_and_ordered_items(saved):
    client, pid = saved
    body = client.get(f"/purchases/{pid}").json()
    assert body["status"] == "ok" and body["total_amount"] == 12.9
    assert body["store"]["name"] == "Mercado" and body["payment_method"] == "PIX"
    assert [i["raw_description"] for i in body["items"]] == ["ARROZ", "BANANA"]
    # BANANA has no unit price: it gets flagged for a look; ARROZ (2 × 3.50 = 7.00) doesn't.
    assert [i["flagged"] for i in body["items"]] == [False, True]
    assert client.get("/purchases").json()[0]["id"] == pid


def test_other_users_purchase_is_404(saved, redis_client):
    client, pid = saved
    redis_client.set(
        "session:abc",
        upsert_user({"sub": f"x-{uuid4()}", "email": "x", "name": "", "picture": ""}),
    )
    assert client.get(f"/purchases/{pid}").status_code == 404
    item = {"new_product": {"name": "X"}, "quantity": 1, "unit": "UN", "unit_price": 1}
    assert client.post(f"/purchases/{pid}/items", json=item).status_code == 404


def test_editing_an_item_recomputes_total_and_status(saved):
    client, pid = saved
    banana = client.get(f"/purchases/{pid}").json()["items"][1]
    url = f"/purchases/{pid}/items/{banana['id']}"
    # No product picked (only the numbers fixed): stays without a product.
    numbers_only = {"quantity": 0.5, "unit": "KG", "unit_price": 10}
    assert client.patch(url, json=numbers_only).json()["items"][1]["product"] is None

    # "Criar novo produto" creates it, with brand and package, and links it.
    banana = {"name": f"Banana {uuid4()}", "brand": "Sítio", "package_size": 1000, "package_unit": "g"}
    edit = {"new_product": banana, "quantity": 0.5, "unit": "KG", "unit_price": 10}
    body = client.patch(url, json=edit).json()
    item = body["items"][1]
    assert {k: item["product"][k] for k in banana} == banana
    assert (item["total_amount"], item["flagged"]) == (5.0, False)
    assert item["raw_description"] == "BANANA"  # what the receipt says is never overwritten
    assert body["status"] == "needs_review"  # 7.00 + 5.00 ≠ 12.90

    # Picking an existing product links that one; it shows up in the picker's list.
    with psycopg.connect(DATABASE_URL) as conn:  # its own, so an empty database works too
        other_id = str(save_node.upsert_product(conn, f"Outro {uuid4()}", None, None, None))
    other = next(p for p in client.get("/products").json() if p["id"] == other_id)
    pick = {"product_id": other["id"], "quantity": 0.5, "unit": "KG", "unit_price": 11.8}
    body = client.patch(url, json=pick).json()  # 0.5 × 11.80 = 5.90 → adds up again
    assert body["items"][1]["product"]["id"] == other["id"] and body["status"] == "ok"


def test_unknown_product_is_rejected(saved):
    client, pid = saved
    banana = client.get(f"/purchases/{pid}").json()["items"][1]
    pick = {"product_id": str(uuid4()), "quantity": 1, "unit": "UN", "unit_price": 1}
    assert client.patch(f"/purchases/{pid}/items/{banana['id']}", json=pick).status_code == 422


def test_adding_an_item_goes_last_and_rechecks(saved):
    client, pid = saved
    new = {"new_product": {"name": "Sacola"}, "quantity": 1, "unit": "UN", "unit_price": 0.1}
    response = client.post(f"/purchases/{pid}/items", json=new)
    assert response.status_code == 201
    body = response.json()
    assert (
        body["items"][-1]["product"]["name"] == "Sacola"
        and body["items"][-1]["raw_description"] is None
    )
    assert body["status"] == "needs_review"  # 13.00 ≠ 12.90


def test_invalid_item_is_rejected(saved):
    client, pid = saved
    bad = {"new_product": {"name": "   "}, "quantity": -1, "unit": "UN", "unit_price": 1}
    assert client.post(f"/purchases/{pid}/items", json=bad).status_code == 422
    size_without_unit = {"name": "Café", "package_size": 500}
    bad = {"new_product": size_without_unit, "quantity": 1, "unit": "UN", "unit_price": 1}
    assert client.post(f"/purchases/{pid}/items", json=bad).status_code == 422
    no_product = {"quantity": 1, "unit": "UN", "unit_price": 1}
    assert client.post(f"/purchases/{pid}/items", json=no_product).status_code == 422
    assert client.get("/purchases/not-a-uuid").status_code == 422


def test_correcting_the_total_rechecks(saved):
    client, pid = saved
    body = client.patch(f"/purchases/{pid}", json={"total_amount": 13}).json()
    assert (body["total_amount"], body["status"]) == (
        13.0,
        "needs_review",
    )  # items add up to 12.90
    assert (
        client.patch(f"/purchases/{pid}", json={"total_amount": 12.9}).json()["status"]
        == "ok"
    )
    assert (
        client.patch(f"/purchases/{pid}", json={"total_amount": -1}).status_code == 422
    )
    assert (
        client.patch(f"/purchases/{uuid4()}", json={"total_amount": 1}).status_code
        == 404
    )


def test_deleting_an_item_rechecks(saved):
    client, pid = saved
    banana = client.get(f"/purchases/{pid}").json()["items"][1]
    body = client.delete(f"/purchases/{pid}/items/{banana['id']}").json()
    assert [i["raw_description"] for i in body["items"]] == ["ARROZ"]
    assert body["status"] == "needs_review"  # 7.00 ≠ 12.90
    assert client.delete(f"/purchases/{pid}/items/{banana['id']}").status_code == 404


def test_deleting_a_purchase_removes_rows_and_photo(saved, monkeypatch):
    client, pid = saved
    s3 = FakeS3WithDelete()
    monkeypatch.setattr(purchases_api, "s3", s3)
    assert client.delete(f"/purchases/{pid}").status_code == 204
    assert client.get(f"/purchases/{pid}").status_code == 404
    assert len(s3.deleted) == 1 and s3.deleted[0].endswith(f"{pid}.jpg")
    assert client.delete(f"/purchases/{pid}").status_code == 404


def test_s3_failure_keeps_the_purchase(saved, monkeypatch):
    client, pid = saved
    monkeypatch.setattr(purchases_api, "s3", FakeS3WithDelete(fail_delete=True))
    with pytest.raises(RuntimeError):
        client.delete(f"/purchases/{pid}")
    assert client.get(f"/purchases/{pid}").status_code == 200


def test_items_carry_the_previous_purchase_unit_price(saved, redis_client):
    """Price trend: each item knows what the same product cost in the user's purchase before it."""
    client, first = saved
    item = {"new_product": {"name": f"Arroz {uuid4()}"}, "quantity": 1, "unit": "UN", "unit_price": 10}
    arroz = client.post(f"/purchases/{first}/items", json=item).json()["items"][-1]
    assert arroz["previous_unit_price"] is None  # first time bought: nothing to compare

    later = state(redis_client.get("session:abc"))
    later["data"] = DATA.model_copy(
        update={"purchase": Purchase(total_amount=24, purchased_at=datetime(2025, 4, 1, 10))}
    )
    save_node.node_save(later)
    second = str(later["uuid"])
    linked = {"product_id": arroz["product"]["id"], "quantity": 2, "unit_price": 12}
    lines = client.post(f"/purchases/{second}/items", json={**linked, "unit": "UN"}).json()["items"]
    assert lines[-1]["previous_unit_price"] == 10
    # Sold by another unit: kg and un prices don't compare.
    lines = client.post(f"/purchases/{second}/items", json={**linked, "unit": "KG"}).json()["items"]
    assert lines[-1]["previous_unit_price"] is None


def test_product_brand_and_logo_come_from_brands(saved):
    client, pid = saved
    banana = client.get(f"/purchases/{pid}").json()["items"][1]
    brand = f"Sítio {uuid4()}"
    new = {"name": f"Banana {uuid4()}", "brand": brand, "package_size": 1000, "package_unit": "g"}
    edit = {"new_product": new, "quantity": 0.5, "unit": "KG", "unit_price": 10}
    client.patch(f"/purchases/{pid}/items/{banana['id']}", json=edit)
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("UPDATE brands SET logo = 'https://x.com/sitio.png' WHERE name = %s", (brand,))

    product = client.get(f"/purchases/{pid}").json()["items"][1]["product"]
    assert (product["brand"], product["brand_logo"]) == (brand, "https://x.com/sitio.png")
    listed = next(p for p in client.get("/products").json() if p["id"] == product["id"])
    assert (listed["brand"], listed["brand_logo"]) == (brand, "https://x.com/sitio.png")
    # Item without a product: still null, no crash on the join.
    assert client.get(f"/purchases/{pid}").json()["items"][0]["product"] is None
