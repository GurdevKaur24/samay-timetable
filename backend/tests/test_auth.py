from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME
from app.main import create_app

from .conftest import DEMO, sign_in


def test_sign_in_returns_own_college_and_sets_private_cookie(make_client):
    client = make_client()
    r = sign_in(client, "demo-eng")
    assert r.status_code == 200
    assert r.json()["college"]["name"] == "Demo Engineering College"
    cookie = r.headers["set-cookie"]
    assert COOKIE_NAME in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()


def test_wrong_password_and_unknown_email_get_the_same_message(make_client):
    client = make_client()
    wrong = sign_in(client, "demo-eng", password="not-the-password")
    unknown = client.post("/api/auth/login", json={"email": "nobody@nowhere.example", "password": "x"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert COOKIE_NAME not in client.cookies


def test_email_is_not_case_sensitive(make_client):
    client = make_client()
    user = DEMO["demo-eng"]
    r = client.post("/api/auth/login", json={"email": "  " + user["email"].upper() + " ", "password": user["password"]})
    assert r.status_code == 200


def test_me_requires_sign_in(make_client):
    r = make_client().get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Please sign in."


def test_sign_out_ends_the_session(eng):
    token = eng.cookies[COOKIE_NAME]
    assert eng.post("/api/auth/logout").status_code == 200
    eng.cookies.set(COOKIE_NAME, token)  # even if someone kept the old cookie
    assert eng.get("/api/auth/me").status_code == 401


def test_expired_session_is_refused(app, make_client):
    user = app.state.db.find_user_by_email(DEMO["demo-eng"]["email"])
    token = app.state.db.create_session(user["id"], seconds=-1)
    client = make_client()
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/auth/me").status_code == 401


def test_made_up_session_is_refused(make_client):
    client = make_client()
    client.cookies.set(COOKIE_NAME, "made-up-token")
    assert client.get("/api/auth/me").status_code == 401


def test_too_many_wrong_passwords_are_slowed_down(make_client):
    client = make_client()
    for _ in range(5):
        assert sign_in(client, "demo-eng", password="wrong").status_code == 401
    r = sign_in(client, "demo-eng")  # even the right password waits now
    assert r.status_code == 429


def test_demo_accounts_sign_in_with_one_click(make_client):
    client = make_client()
    accounts = client.get("/api/auth/demo-accounts").json()["accounts"]
    assert {a["college"] for a in accounts} == {"Demo Engineering College", "Guru Nanak Dev Engineering College (demo)"}
    assert {a["role"] for a in accounts if a["college"].startswith("Guru Nanak")} == {"coordinator", "hod", "teacher"}
    assert all("password" not in a for a in accounts)
    r = client.post("/api/auth/demo", json={"email": accounts[0]["email"]})
    assert r.status_code == 200 and COOKIE_NAME in client.cookies
    assert client.get("/api/college").json()["name"] == accounts[0]["college"]


def test_demo_sign_in_only_works_for_demo_accounts(app, make_client):
    app.state.db.add_user("real.person@college.example", "Real Person", "coordinator", "demo-eng", "a-real-password")
    r = make_client().post("/api/auth/demo", json={"email": "real.person@college.example"})
    assert r.status_code == 404


def test_demo_sign_in_is_completely_off_when_switched_off(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "prod.db", demo_login=False))
    assert client.get("/api/health").json()["demo_login"] is False
    assert client.get("/api/auth/demo-accounts").status_code == 404
    assert client.post("/api/auth/demo", json={"email": DEMO["demo-eng"]["email"]}).status_code == 404


def test_passwords_and_session_tokens_are_not_stored_in_plain_text(app, eng):
    with app.state.db.connect() as conn:
        stored_password = conn.execute("SELECT password_hash FROM users WHERE email = ?", (DEMO["demo-eng"]["email"],)).fetchone()[0]
        stored_tokens = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert DEMO["demo-eng"]["password"] not in stored_password and stored_password.startswith("scrypt$")
    assert eng.cookies[COOKIE_NAME] not in stored_tokens
