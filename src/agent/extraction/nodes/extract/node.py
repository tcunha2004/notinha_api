import base64

from langchain_core.messages import HumanMessage, SystemMessage

from agent.extraction.config import LLM
from agent.extraction.nodes.extract.models import ExtractionResponse
from agent.extraction.nodes.extract.prompts import (
    extract_system_prompt,
    extract_user_prompt,
)
from agent.extraction.state import GraphState


def node_extract_data(state: GraphState):
    response: ExtractionResponse | None = LLM.with_structured_output(  # type: ignore
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

    if response is None or response.error or response.data is None:
        reason = response.error if response else "model returned no output"
        raise ValueError(f"Invoice extraction failed: {reason or 'no data returned'}")

    return {"data": response.data}
