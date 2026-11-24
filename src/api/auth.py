from typing import Annotated

from config import GOOGLE_CLIENT_ID
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests
from google.oauth2 import id_token

bearer = HTTPBearer()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> str:
    """Validate the Google ID token and return its `sub` (the user's stable ID)."""
    try:
        claims = id_token.verify_oauth2_token(
            credentials.credentials, requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return claims["sub"]
