import base64
from typing import Literal

from agent.extraction.config import LLM
from agent.extraction.nodes.extract.models import ExtractionResponse
from agent.extraction.nodes.extract.prompts import (
    extract_system_prompt,
    extract_user_prompt,
)
from agent.extraction.state import GraphState, SaveStatus
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

MAX_EXTRACTION_TRIES = 2


class UnreadableInvoice(Exception):
    """Nothing at all could be read from the image (illegible, or not an NFC-e)."""


def node_extract_data(state: GraphState) -> Command[Literal["extract", "save"]]:
    response: ExtractionResponse = LLM.with_structured_output(  # type: ignore
        ExtractionResponse
    ).invoke(
        [
            SystemMessage(content=extract_system_prompt),
            HumanMessage(
                content=[
                    {
                        "type": "image",
                        "base64": base64.b64encode(state["image"]).decode(),
                        "mime_type": state["media_type"],
                    },
                    {"type": "text", "text": extract_user_prompt},
                ]
            ),
        ]
    )

    if response is None or response.data is None:
        raise UnreadableInvoice("Could not extract any data from the invoice image")

    if response.error:
        tries = state.get("extraction_tries", 0) + 1
        if tries >= MAX_EXTRACTION_TRIES:
            return Command(
                update={
                    "data": response.data,
                    "extraction_tries": tries,
                    "save_status": SaveStatus.REVIEW,
                },
                goto="save",
            )
        return Command(update={"extraction_tries": tries}, goto="extract")

    return Command(
        update={"data": response.data, "save_status": SaveStatus.OK}, goto="save"  # type: ignore
    )
