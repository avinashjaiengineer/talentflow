from tests.conftest import ADMIN


def test_api_requires_sign_in(anon):
    for path in ("/api/jobs", "/api/candidates", "/api/approvals", "/api/events", "/api/stats", "/api/auth/me"):
        assert anon.get(path).status_code == 401, path
    assert anon.post("/api/jobs", json={"title": "x", "description": "y"}).status_code == 401


def test_login_logout_and_me(anon):
    assert anon.post("/api/auth/login", json={**ADMIN, "password": "wrong-password"}).status_code == 401
    r = anon.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200
    assert "tf_session" in r.cookies
    assert "httponly" in r.headers["set-cookie"].lower()
    assert anon.get("/api/auth/me").json()["role"] == "admin"
    anon.post("/api/auth/logout")
    assert anon.get("/api/auth/me").status_code == 401


def test_bearer_token_for_api_clients(anon):
    token = anon.post("/api/auth/login", json=ADMIN).json()["token"]
    anon.cookies.clear()
    assert anon.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert anon.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_login_is_rate_limited(anon):
    bad = {**ADMIN, "password": "nope-nope-nope"}
    codes = [anon.post("/api/auth/login", json=bad).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429
    # even the right password is refused while blocked
    assert anon.post("/api/auth/login", json=ADMIN).status_code == 429


def test_admin_manages_users_and_recruiters_cannot(client, anon):
    r = client.post("/api/users", json={"email": "Rita@Example.com", "name": "Rita", "password": "recruiter-pass-1"})
    assert r.status_code == 201
    rita = r.json()
    assert rita["email"] == "rita@example.com" and rita["role"] == "recruiter"
    assert client.post("/api/users", json={"email": "rita@example.com", "name": "R", "password": "recruiter-pass-1"}).status_code == 409

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "rita@example.com", "password": "recruiter-pass-1"}).status_code == 200
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"email": "x@example.com", "name": "X", "password": "whatever-123"}).status_code == 403


def test_deactivating_a_user_ends_their_sessions(client):
    rita = client.post("/api/users", json={"email": "rita@example.com", "name": "Rita", "password": "recruiter-pass-1"}).json()
    token = client.post("/api/auth/login", json={"email": "rita@example.com", "password": "recruiter-pass-1"}).json()["token"]
    client.cookies.clear()
    client.post("/api/auth/login", json=ADMIN)
    assert client.patch(f"/api/users/{rita['id']}", json={"is_active": False}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_password_change_revokes_old_tokens(client):
    old = client.post("/api/auth/login", json=ADMIN).json()["token"]
    r = client.post("/api/auth/password", json={"current_password": ADMIN["password"], "new_password": "a-brand-new-pass"})
    assert r.status_code == 204
    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": ADMIN["email"], "password": "a-brand-new-pass"}).status_code == 200


def test_admin_cannot_lock_themselves_out(client):
    me = client.get("/api/auth/me").json()
    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 400


def test_security_headers(anon):
    r = anon.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-request-id"]
