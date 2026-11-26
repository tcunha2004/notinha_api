from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from agent.extraction.graph import Graph
from agent.extraction.nodes.extract.node import UnreadableInvoice
from agent.extraction.nodes.save.node import DuplicatePurchase
from agent.extraction.state import MediaType
from api.auth import current_user_id

router = APIRouter(prefix="/invoice", tags=["invoice"])

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

graph = Graph()


@router.post("/upload_invoice")
def upload_invoice(
    image: UploadFile, user_id: Annotated[str, Depends(current_user_id)]
):
    if image.content_type not in set(MediaType):
        raise HTTPException(status_code=400, detail="The file must be an image")
    if image.size and image.size > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="The image must have 10 MB maximum")

    uuid = uuid4()
    try:
        # The save node writes the image to S3 and the data to Postgres.
        result = graph.compiler.invoke(
            {
                "uuid": uuid,
                "user_id": user_id,
                "image": image.file.read(),
                "media_type": MediaType(image.content_type),
            }
        )
    except UnreadableInvoice as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except DuplicatePurchase as e:
        # The frontend uses purchase_id to open the purchase that already exists.
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "purchase_id": str(e.purchase_id)},
        ) from e
    return {"id": uuid, "status": result["save_status"]}
