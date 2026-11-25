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
    redis_client.set("session:abc", "user-1")
    client.cookies.set("session", "abc")
    # 400 comes from the route's own image check, so auth already passed (and S3 is never hit).
    response = upload_text_file(client)
    assert response.status_code == 400
    assert response.json()["detail"] == "The file must be an image"


def login(client):
    return client.post("/auth/google", json={"credential": "valid-token"})


def test_login_creates_session_and_sets_httponly_cookie(client, redis_client, google_claims):
    response = login(client)
    assert response.status_code == 200
    assert response.json() == {
        "email": "ana@example.com",
        "name": "Ana Souza",
        "picture": "https://example.com/ana.png",
    }
    cookie = response.headers["set-cookie"]
    assert "session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=604800" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie
    sid = client.cookies["session"]
    assert redis_client.get(f"session:{sid}") == "user-google-123"  # only users.id is stored
    assert 604790 < redis_client.ttl(f"session:{sid}") <= 604800


def test_login_rejects_invalid_token(client, google_claims):
    response = client.post("/auth/google", json={"credential": "forged"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_login_rejects_unverified_email(client, redis_client, google_claims):
    google_claims["email_verified"] = False
    assert login(client).status_code == 401
    assert redis_client.keys("session:*") == []


def test_login_replaces_previous_session(client, redis_client, google_claims):
    login(client)
    first = client.cookies["session"]
    login(client)
    assert redis_client.get(f"session:{first}") is None
    assert len(redis_client.keys("session:*")) == 1


def test_me_returns_user(client, google_claims):
    login(client)
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "ana@example.com"


def test_login_creates_the_user(client, users_db, google_claims):
    login(client)
    assert users_db["user-google-123"]["picture"] == "https://example.com/ana.png"


def test_me_reads_the_profile_from_the_db(client, users_db, google_claims):
    login(client)
    users_db["user-google-123"]["name"] = "Ana S."  # profile changed after login
    assert client.get("/auth/me").json()["name"] == "Ana S."


def test_me_is_401_when_the_user_no_longer_exists(client, users_db, google_claims):
    login(client)
    users_db.clear()
    assert client.get("/auth/me").status_code == 401


def test_me_without_session_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_logout_deletes_session_and_cookie(client, redis_client, google_claims):
    login(client)
    sid = client.cookies["session"]
    response = client.post("/auth/logout")
    assert response.status_code == 204
    assert redis_client.get(f"session:{sid}") is None
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.get("/auth/me").status_code == 401


def test_logout_without_session_is_204(client):
    assert client.post("/auth/logout").status_code == 204
