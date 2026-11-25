import os

# Config reads these at import time; set them before importing the app.
# Plain assignment for the client ID: a real value from .env would break the audience assert.
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")

import fakeredis
import pytest
from fastapi.testclient import TestClient

from api.auth import get_redis
from api.main import api


@pytest.fixture(autouse=True)
def users_db(monkeypatch):
    """In-memory users table, so the API tests don't need Postgres.
    The real SQL is covered in test_save_node.py."""
    users: dict[str, dict] = {}

    def upsert(claims):
        user_id = f"user-{claims['sub']}"
        users[user_id] = {k: claims.get(k, "") for k in ("email", "name", "picture")}
        return user_id

    monkeypatch.setattr("api.auth.upsert_user", upsert)
    monkeypatch.setattr("api.auth.load_user", users.get)
    return users


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def client(redis_client):
    api.dependency_overrides[get_redis] = lambda: redis_client
    yield TestClient(api)
    api.dependency_overrides.clear()


@pytest.fixture
def google_claims(monkeypatch):
    claims = {
        "sub": "google-123",
        "email": "ana@example.com",
        "email_verified": True,
        "name": "Ana Souza",
        "picture": "https://example.com/ana.png",
    }

    def fake_verify(token, request, audience):
        if token != "valid-token":
            raise ValueError("bad token")
        assert audience == "test-client-id"
        return claims

    monkeypatch.setattr("api.auth.id_token.verify_oauth2_token", fake_verify)
    return claims
