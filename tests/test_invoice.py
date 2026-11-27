"""What the upload endpoint answers for each graph outcome (the frontend depends on these codes)."""

import asyncio
import io
import threading
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from langgraph.types import Command
from starlette.datastructures import Headers

from agent.extraction import graph as graph_module
from agent.extraction.nodes.extract.node import InvalidInvoice, UnreadableInvoice
from agent.extraction.nodes.save.node import DuplicatePurchase
from agent.extraction.state import SaveStatus
from api.invoice import router as invoice_router


@pytest.fixture
def upload(client, redis_client, monkeypatch):
    redis_client.set("session:abc", "user-1")
    client.cookies.set("session", "abc")

    def send(graph_invoke):
        async def ainvoke(state):
            return graph_invoke(state)

        monkeypatch.setattr(invoice_router.graph.compiler, "ainvoke", ainvoke)
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

    response = send(invoke)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unreadable"


def test_not_a_grocery_receipt_is_422_invalid(upload):
    send = upload

    def invoke(_state):
        raise InvalidInvoice("The image is not a supermarket or pharmacy receipt")

    response = send(invoke)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid"


def test_duplicate_invoice_is_409_with_existing_purchase_id(upload):
    send = upload
    existing = uuid4()

    def invoke(_state):
        raise DuplicatePurchase(existing)

    response = send(invoke)
    assert response.status_code == 409
    assert response.json()["detail"]["purchase_id"] == str(existing)


def read_receipt(monkeypatch, *, reading_takes: float, leaves_mid_reading: bool):
    """Calls the endpoint over the real graph wiring, with fake nodes.
    Returns the HTTP status and the purchases that got saved."""
    reading = threading.Event()
    saved = []

    def extract(_state):
        reading.set()
        time.sleep(reading_takes)  # the LLM reading the photo
        return Command(update={"save_status": SaveStatus.OK}, goto="store_logo")

    monkeypatch.setattr(graph_module, "node_extract_data", extract)
    monkeypatch.setattr(graph_module, "node_store_logo", lambda _s: {})
    monkeypatch.setattr(graph_module, "node_save", lambda s: saved.append(s["uuid"]) or {})
    monkeypatch.setattr(invoice_router, "graph", graph_module.Graph())

    class Request:
        async def is_disconnected(self):
            return leaves_mid_reading and reading.is_set()

    image = UploadFile(
        io.BytesIO(b"jpeg-bytes"), size=10, headers=Headers({"content-type": "image/jpeg"})
    )
    try:
        asyncio.run(invoice_router.upload_invoice(Request(), image, "user-1"))
        status = 200
    except HTTPException as error:
        status = error.status_code
    time.sleep(reading_takes)  # let the reading thread finish: save must still not run
    return status, saved


def test_reading_to_the_end_saves(monkeypatch):
    # Control case: proves the fake graph does reach save.
    status, saved = read_receipt(monkeypatch, reading_takes=0, leaves_mid_reading=False)
    assert (status, len(saved)) == (200, 1)


def test_user_leaving_mid_reading_saves_nothing(monkeypatch):
    status, saved = read_receipt(monkeypatch, reading_takes=1, leaves_mid_reading=True)
    assert (status, saved) == (499, [])
