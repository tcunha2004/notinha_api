import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile

from agent.brand_logo import fill_brand_logos
from agent.extraction.graph import Graph
from agent.extraction.nodes.extract.node import InvalidInvoice, UnreadableInvoice
from agent.extraction.nodes.save.node import DuplicatePurchase
from agent.extraction.state import MediaType
from api.auth import current_user_id

router = APIRouter(prefix="/invoice", tags=["invoice"])

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

graph = Graph()


@router.post("/upload_invoice")
async def upload_invoice(
    request: Request,
    background_tasks: BackgroundTasks,
    image: UploadFile,
    user_id: Annotated[str, Depends(current_user_id)],
):
    if image.content_type not in set(MediaType):
        raise HTTPException(status_code=400, detail="The file must be an image")
    if image.size and image.size > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="The image must have 10 MB maximum")

    uuid = uuid4()
    # The save node writes the image to S3 and the data to Postgres.
    task = asyncio.create_task(
        graph.compiler.ainvoke(
            {
                "uuid": uuid,
                "user_id": user_id,
                "image": await image.read(),
                "media_type": MediaType(image.content_type),
            }
        )
    )
    # The user left mid-reading (Cancelar aborts the fetch): stop the graph so nothing is saved.
    # A node already running finishes in its thread, but the next one (save) never starts.
    while not task.done():
        if await request.is_disconnected():
            task.cancel()
            raise HTTPException(status_code=499, detail="Client closed the request")
        await asyncio.wait({task}, timeout=0.5)
    try:
        result = task.result()
    # Both are 422 (nothing saved); `reason` tells the frontend which message to show.
    except UnreadableInvoice as e:
        raise HTTPException(
            status_code=422, detail={"message": str(e), "reason": "unreadable"}
        ) from e
    except InvalidInvoice as e:
        raise HTTPException(
            status_code=422, detail={"message": str(e), "reason": "invalid"}
        ) from e
    except DuplicatePurchase as e:
        # The frontend uses purchase_id to open the purchase that already exists.
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "purchase_id": str(e.purchase_id)},
        ) from e
    # Runs after the response, so "Processando" doesn't wait for the logos.
    background_tasks.add_task(fill_brand_logos)
    return {"id": uuid, "status": result["save_status"]}
