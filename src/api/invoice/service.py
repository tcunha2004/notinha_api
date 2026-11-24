import logging
import mimetypes
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile

from api.config.config import AWS_REGION, S3_BUCKET_NAME

logger = logging.getLogger(__name__)

s3 = boto3.client("s3", region_name=AWS_REGION)


def upload_invoice_image(user_id: str, image: UploadFile, uuid: uuid.UUID) -> str:
    """Upload the image to S3 at `{user_id}/{uuid}.ext` and return that key."""
    extension = mimetypes.guess_extension(image.content_type) or ""  # type: ignore
    key = f"{user_id}/{uuid}{extension}"
    try:
        s3.upload_fileobj(
            image.file,
            S3_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": image.content_type},
        )
    except (BotoCoreError, ClientError) as e:
        logger.exception("Failed to upload %s to S3", key)
        raise HTTPException(
            status_code=502, detail="Could not save the image, please try again"
        ) from e
    return key
