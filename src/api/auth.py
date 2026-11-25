import secrets
from typing import Annotated

import psycopg
import redis
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from google.auth.transport import requests
from google.oauth2 import id_token
from psycopg.rows import dict_row
from pydantic import BaseModel

from api.config.config import COOKIE_SECURE, DATABASE_URL, GOOGLE_CLIENT_ID, REDIS_URL

SESSION_COOKIE = "session"
SESSION_TTL = 604800  # 7 days, no sliding renewal

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_redis() -> redis.Redis:
    return _redis


def upsert_user(claims: dict) -> str:
    """Create the user on the first login, refresh their Google profile on the next ones.
    Returns our own users.id, which is what the session and every other table use."""
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            """INSERT INTO users (google_sub, email, name, picture) VALUES (%s, %s, %s, %s)
               ON CONFLICT (google_sub) DO UPDATE SET
                   email = EXCLUDED.email, name = EXCLUDED.name, picture = EXCLUDED.picture
               RETURNING id""",
            (claims["sub"], claims["email"], claims.get("name", ""), claims.get("picture", "")),
        ).fetchone()
    return str(row[0])  # type: ignore[index]


def load_user(user_id: str) -> dict | None:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        return conn.execute(
            "SELECT email, name, picture FROM users WHERE id = %s", (user_id,)
        ).fetchone()


def current_user_id(
    session: Annotated[str | None, Cookie()] = None,
    r: redis.Redis = Depends(get_redis),
) -> str:
    """Resolve the session cookie to users.id through Redis; 401 when missing, expired or tampered."""
    user_id = r.get(f"session:{session}") if session else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id  # type: ignore[return-value]


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

    user_id = upsert_user(claims)

    if session:  # a new login always gets a new session ID; don't leave the old one orphaned
        r.delete(f"session:{session}")
    sid = secrets.token_urlsafe(32)
    r.set(f"session:{sid}", user_id, ex=SESSION_TTL)
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    return {
        "email": claims["email"],
        "name": claims.get("name", ""),
        "picture": claims.get("picture", ""),
    }


@router.get("/me", response_model=UserOut)
def me(user_id: Annotated[str, Depends(current_user_id)]):
    user = load_user(user_id)
    if user is None:  # the session outlived the user row
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


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
