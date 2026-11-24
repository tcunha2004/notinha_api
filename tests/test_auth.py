import json

SESSION = {"sub": "google-123", "email": "ana@example.com", "name": "Ana Souza", "picture": ""}


def upload_text_file(client):
    return client.post(
        "/invoice/upload_invoice",
        files={"image": ("nota.txt", b"not an image", "text/plain")},
    )


def test_no_cookie_is_401(client):
    assert upload_text_file(client).status_code == 401


def test_unknown_session_is_401(client):
    client.cookies.set("session", "does-not-exist")
    assert upload_text_file(client).status_code == 401


def test_valid_session_passes_auth(client, redis_client):
    redis_client.set("session:abc", json.dumps(SESSION))
    client.cookies.set("session", "abc")
    # 400 comes from the route's own image check, so auth already passed (and S3 is never hit).
    response = upload_text_file(client)
    assert response.status_code == 400
    assert response.json()["detail"] == "The file must be an image"
