import json
from typing import Annotated

import redis
from fastapi import Cookie, Depends, HTTPException

from api.config.config import REDIS_URL

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
