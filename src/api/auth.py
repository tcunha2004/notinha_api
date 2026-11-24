import json
import secrets
from typing import Annotated

import redis
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from google.auth.transport import requests
from google.oauth2 import id_token
from pydantic import BaseModel

from api.config.config import COOKIE_SECURE, GOOGLE_CLIENT_ID, REDIS_URL

SESSION_COOKIE = "session"
SESSION_TTL = 604800  # 7 days, no sliding renewal

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_redis() -> redis.Redis:
    return _redis


def current_session(
    session: Annotated[str | None, Cookie()] = None,
    r: redis.Redis = Depends(get_redis),
) -> dict:
    """Resolve the session cookie through Redis; 401 when missing, expired or tampered."""
    raw = r.get(f"session:{session}") if session else None
    if raw is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return json.loads(raw)


def get_current_user(session_data: Annotated[dict, Depends(current_session)]) -> str:
    """Return the user's stable ID (Google `sub`)."""
    return session_data["sub"]


router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleLogin(BaseModel):
    credential: str


class UserOut(BaseModel):
    email: str
    name: str
    picture: str


@router.post("/google", response_model=UserOut)
def login(
    body: GoogleLogin,
    response: Response,
    session: Annotated[str | None, Cookie()] = None,
    r: redis.Redis = Depends(get_redis),
):
    """Exchange a Google ID token for our own session cookie."""
    try:
        claims = id_token.verify_oauth2_token(
            body.credential, requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Email not verified")

    if (
        session
    ):  # a new login always gets a new session ID; don't leave the old one orphaned
        r.delete(f"session:{session}")
    user = {
        "sub": claims["sub"],
        "email": claims["email"],
        "name": claims.get("name", ""),
        "picture": claims.get("picture", ""),
    }
    sid = secrets.token_urlsafe(32)
    r.set(f"session:{sid}", json.dumps(user), ex=SESSION_TTL)
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    return user


@router.get("/me", response_model=UserOut)
def me(session_data: Annotated[dict, Depends(current_session)]):
    return session_data


@router.post("/logout", status_code=204)
def logout(
    session: Annotated[str | None, Cookie()] = None,
    r: redis.Redis = Depends(get_redis),
):
    if session:
        r.delete(f"session:{session}")
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=COOKIE_SECURE
    )
    return response
