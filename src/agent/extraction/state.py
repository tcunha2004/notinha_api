from enum import StrEnum
from typing import NotRequired, TypedDict
from uuid import UUID

from agent.extraction.nodes.extract.models import ExtractionOutput


class MediaType(StrEnum):
    JPG = "image/jpeg"
    JPEG = "image/jpeg"
    PNG = "image/png"


class GraphState(TypedDict):
    uuid: UUID
    user_id: str
    image: bytes
    media_type: MediaType
    data: NotRequired[ExtractionOutput]
