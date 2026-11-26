"""What the upload endpoint answers for each graph outcome (the frontend depends on these codes)."""

from uuid import uuid4

import pytest

from agent.extraction.nodes.extract.node import UnreadableInvoice
from agent.extraction.nodes.save.node import DuplicatePurchase
from agent.extraction.state import SaveStatus
from api.invoice import router as invoice_router


@pytest.fixture
def upload(client, redis_client, monkeypatch):
    redis_client.set("session:abc", "user-1")
    client.cookies.set("session", "abc")

    def send(graph_invoke):
        monkeypatch.setattr(invoice_router.graph.compiler, "invoke", graph_invoke)
        return client.post(
            "/invoice/upload_invoice",
            files={"image": ("nota.jpg", b"jpeg-bytes", "image/jpeg")},
        )

    return send


def test_saved_purchase_returns_id_and_status(upload):
    send = upload
    seen = {}

    def invoke(state):
        seen.update(state)
        return {"save_status": SaveStatus.REVIEW}

    response = send(invoke)
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    assert response.json()["id"] == str(seen["uuid"])
    assert seen["user_id"] == "user-1"  # the session's users.id reaches the graph


def test_unreadable_image_is_422(upload):
    send = upload

    def invoke(_state):
        raise UnreadableInvoice("Could not extract any data from the invoice image")

    assert send(invoke).status_code == 422


def test_duplicate_invoice_is_409_with_existing_purchase_id(upload):
    send = upload
    existing = uuid4()

    def invoke(_state):
        raise DuplicatePurchase(existing)

    response = send(invoke)
    assert response.status_code == 409
    assert response.json()["detail"]["purchase_id"] == str(existing)
