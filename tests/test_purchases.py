"""Purchase routes against the real Postgres: reading, ownership, item edits and the status re-check."""

from uuid import uuid4

import pytest
from test_save_node import (  # importing it also skips this file when Postgres is down
    FakeS3,
    state,
)

from agent.extraction.nodes.save import node as save_node
from api.purchases import router as purchases_api
from api.auth import upsert_user  # bound before conftest's in-memory patch


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
    item = {"description": "X", "quantity": 1, "unit": "UN", "unit_price": 1}
    assert client.post(f"/purchases/{pid}/items", json=item).status_code == 404


def test_editing_an_item_recomputes_total_and_status(saved):
    client, pid = saved
    banana = client.get(f"/purchases/{pid}").json()["items"][1]
    edit = {
        "description": "Banana prata",
        "quantity": 0.5,
        "unit": "KG",
        "unit_price": 10,
        "discount": 0,
    }
    body = client.patch(f"/purchases/{pid}/items/{banana['id']}", json=edit).json()
    item = body["items"][1]
    assert (item["description"], item["total_amount"], item["flagged"]) == (
        "Banana prata",
        5.0,
        False,
    )
    assert (
        item["raw_description"] == "BANANA"
    )  # what the receipt says is never overwritten
    assert body["status"] == "needs_review"  # 7.00 + 5.00 ≠ 12.90

    edit["unit_price"] = 11.8  # 0.5 × 11.80 = 5.90 → adds up again
    assert (
        client.patch(f"/purchases/{pid}/items/{banana['id']}", json=edit).json()[
            "status"
        ]
        == "ok"
    )


def test_adding_an_item_goes_last_and_rechecks(saved):
    client, pid = saved
    new = {"description": "Sacola", "quantity": 1, "unit": "UN", "unit_price": 0.1}
    response = client.post(f"/purchases/{pid}/items", json=new)
    assert response.status_code == 201
    body = response.json()
    assert (
        body["items"][-1]["description"] == "Sacola"
        and body["items"][-1]["raw_description"] is None
    )
    assert body["status"] == "needs_review"  # 13.00 ≠ 12.90


def test_invalid_item_is_rejected(saved):
    client, pid = saved
    bad = {"description": "", "quantity": -1, "unit": "UN", "unit_price": 1}
    assert client.post(f"/purchases/{pid}/items", json=bad).status_code == 422
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
