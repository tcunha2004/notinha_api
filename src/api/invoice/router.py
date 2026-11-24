from typing import Annotated

from auth import get_current_user
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from invoice import service

router = APIRouter(prefix="/invoice", tags=["invoice"])

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/upload_invoice")
def upload_invoice(
    image: UploadFile, user_id: Annotated[str, Depends(get_current_user)]
):
    if not (image.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="The file must be an image")
    if image.size and image.size > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=413, detail="The image must have 10 MB maximum"
        )

    key = service.upload_invoice_image(user_id, image)
    return {"key": key}
