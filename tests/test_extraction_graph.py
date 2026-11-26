from uuid import uuid4

import pytest

from agent.extraction import graph as graph_module
from agent.extraction.graph import Graph
from agent.extraction.nodes.extract import node as extract_node
from agent.extraction.nodes.extract.models import (
    ExtractionOutput,
    ExtractionResponse,
    Store,
)
from agent.extraction.state import GraphState, MediaType, SaveStatus

FULL = ExtractionOutput(store=Store(name="Mercado", id="1", address="Rua A"))
PARTIAL = ExtractionOutput(store=Store(name="Mercado"))


class FakeLLM:
    """Returns the given responses in order, counting calls."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def with_structured_output(self, _):
        return self

    def invoke(self, _):
        self.calls += 1
        return self.responses.pop(0)


def run(monkeypatch, *responses):
    llm = FakeLLM(*responses)
    monkeypatch.setattr(extract_node, "LLM", llm)
    monkeypatch.setattr(graph_module, "node_save", lambda state: {})  # no DB/S3 here
    monkeypatch.setattr(
        graph_module, "node_store_logo", lambda state: {}
    )  # no web here
    state: GraphState = {
        "uuid": uuid4(),
        "user_id": "u1",
        "image": b"img",
        "media_type": MediaType.JPG,
    }
    return Graph().compiler.invoke(state), llm


def test_no_data_raises(monkeypatch):
    with pytest.raises(extract_node.UnreadableInvoice):
        run(monkeypatch, ExtractionResponse(error=True, data=None))


def test_full_data_saves_ok(monkeypatch):
    result, llm = run(monkeypatch, ExtractionResponse(data=FULL))
    assert (result["save_status"], result["data"], llm.calls) == (
        SaveStatus.OK,
        FULL,
        1,
    )


def test_partial_then_full_retries(monkeypatch):
    result, llm = run(
        monkeypatch,
        ExtractionResponse(error=True, data=PARTIAL),
        ExtractionResponse(data=FULL),
    )
    assert (result["save_status"], result["data"], llm.calls) == (
        SaveStatus.OK,
        FULL,
        2,
    )


def test_partial_until_limit_saves_review(monkeypatch):
    responses = [
        ExtractionResponse(error=True, data=PARTIAL)
    ] * extract_node.MAX_EXTRACTION_TRIES
    result, llm = run(monkeypatch, *responses)
    assert result["save_status"] == SaveStatus.REVIEW
    assert result["data"] == PARTIAL
    assert llm.calls == extract_node.MAX_EXTRACTION_TRIES
