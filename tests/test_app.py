import fakeredis
import psycopg
import redis

from api.auth import get_redis
from api.main import api


def preflight(client, origin):
    return client.options(
        "/auth/me",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


def test_cors_allows_frontend_with_credentials(client):
    response = preflight(client, "http://localhost:5173")
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_other_origins(client):
    response = preflight(client, "https://evil.example")
    assert "access-control-allow-origin" not in response.headers


def test_redis_down_returns_503(client, google_claims):
    server = fakeredis.FakeServer()
    server.connected = False
    api.dependency_overrides[get_redis] = lambda: fakeredis.FakeRedis(server=server)

    response = client.post("/auth/google", json={"credential": "valid-token"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Unavailable service"}

    client.cookies.set("session", "abc")
    assert client.get("/auth/me").status_code == 503


def test_redis_timeout_returns_503(client):
    class HangingRedis:
        def get(self, key):
            raise redis.TimeoutError("Timeout reading from socket")

    api.dependency_overrides[get_redis] = lambda: HangingRedis()
    client.cookies.set("session", "abc")

    response = client.get("/auth/me")
    assert response.status_code == 503
    assert response.json() == {"detail": "Unavailable service"}


def test_postgres_down_returns_503(client, google_claims, monkeypatch):
    def down(_claims):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr("api.auth.upsert_user", down)
    response = client.post("/auth/google", json={"credential": "valid-token"})
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
