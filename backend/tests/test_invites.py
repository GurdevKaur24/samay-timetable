"""Invites (people choose their own password) and forgot password. Links work once, expire, and are stored only as
hashes. Without email set up, the coordinator gets the link to share; with email, Samay sends it."""

import time

import pytest

from .conftest import DEMO

NEW = {"name": "Prof. S. Kaur", "email": "s.kaur@demo-eng.example", "role": "teacher", "teacher": "T02"}


def token_of(link: str) -> str:
    return link.split("=", 1)[1]


def invite(eng, body=NEW):
    r = eng.post("/api/users", json=body)
    assert r.status_code == 201, r.json()
    return r.json()


@pytest.fixture
def outbox(app):
    """Email "set up": messages are captured instead of sent."""
    sent = []
    app.state.send_email = lambda to, subject, text: sent.append({"to": to, "subject": subject, "text": text}) or True
    return sent


# ---- invites ----------------------------------------------------------------------------------------------------
def test_an_invited_person_chooses_their_own_password(eng, make_client):
    r = invite(eng)
    assert r["link"].startswith("/?invite=") and r["emailed"] is False and "yourself" in r["message"]
    listed = next(u for u in eng.get("/api/users").json()["users"] if u["email"] == NEW["email"])
    assert listed["invited"] is True
    phone = make_client()
    assert phone.post("/api/auth/login", json={"email": NEW["email"], "password": "anything-at-all"}).status_code == 401
    info = phone.post("/api/auth/link", json={"token": token_of(r["link"])}).json()
    assert info == {"kind": "invite", "name": "Prof. S. Kaur", "email": NEW["email"], "college": {"name": "Demo Engineering College"}}
    signed_in = phone.post("/api/auth/set-password", json={"token": token_of(r["link"]), "password": "my-own-password"})
    assert signed_in.status_code == 200 and signed_in.json()["user"]["role"] == "teacher"
    assert phone.get("/api/teacher").json()["me"]["name"] == "Prof. S. Kaur"
    assert make_client().post("/api/auth/login", json={"email": NEW["email"], "password": "my-own-password"}).status_code == 200
    assert next(u for u in eng.get("/api/users").json()["users"] if u["email"] == NEW["email"])["invited"] is False


def test_a_link_works_once(eng, make_client):
    token = token_of(invite(eng)["link"])
    assert make_client().post("/api/auth/set-password", json={"token": token, "password": "first-password"}).status_code == 200
    again = make_client().post("/api/auth/set-password", json={"token": token, "password": "second-password"})
    assert again.status_code == 404 and "expired or was already used" in again.json()["detail"]


def test_a_new_invite_replaces_the_old_one(eng, make_client):
    first = invite(eng)
    second = eng.post(f"/api/users/{first['id']}/invite").json()
    assert make_client().post("/api/auth/link", json={"token": token_of(first["link"])}).status_code == 404
    assert make_client().post("/api/auth/link", json={"token": token_of(second["link"])}).status_code == 200


def test_links_expire(app, eng, make_client):
    token = token_of(invite(eng)["link"])
    with app.state.db.connect() as conn:
        conn.execute("UPDATE password_tokens SET expires_at = ?", (time.time() - 1,))
    assert make_client().post("/api/auth/set-password", json={"token": token, "password": "too-late-now"}).status_code == 404


def test_links_are_stored_only_as_hashes(app, eng):
    token = token_of(invite(eng)["link"])
    with app.state.db.connect() as conn:
        stored = [r[0] for r in conn.execute("SELECT token_hash FROM password_tokens")]
    assert stored and token not in stored


def test_invites_are_emailed_when_email_is_set_up(eng, outbox):
    r = invite(eng)
    assert r["emailed"] is True and "We emailed it" in r["message"]
    assert outbox[0]["to"] == NEW["email"] and "Demo Engineering College" in outbox[0]["subject"]
    assert r["link"] in outbox[0]["text"] and "Teacher" in outbox[0]["text"]


def test_a_temporary_password_still_works(eng, make_client):
    r = eng.post("/api/users", json=NEW | {"password": "temporary-pass"})
    assert r.status_code == 201 and "link" not in r.json()
    assert make_client().post("/api/auth/login", json={"email": NEW["email"], "password": "temporary-pass"}).status_code == 200


def test_someone_who_joined_gets_a_reset_link_not_an_invite(eng):
    me = next(u for u in eng.get("/api/users").json()["users"] if u["you"])
    assert eng.post(f"/api/users/{me['id']}/invite").status_code == 409
    assert eng.post(f"/api/users/{me['id']}/reset-link").json()["link"].startswith("/?reset=")


# ---- forgot password ---------------------------------------------------------------------------------------------
def test_forgot_password_never_reveals_whether_an_email_has_an_account(make_client, outbox):
    a = make_client().post("/api/auth/forgot", json={"email": DEMO["demo-eng"]["email"]}).json()
    b = make_client().post("/api/auth/forgot", json={"email": "nobody@nowhere.example"}).json()
    assert a == b and a["email"] is True
    assert [m["to"] for m in outbox] == [DEMO["demo-eng"]["email"]]


def test_forgot_password_resets_and_signs_out_everywhere(eng, make_client, outbox):
    email = DEMO["demo-eng"]["email"]
    make_client().post("/api/auth/forgot", json={"email": email})
    link = next(line for line in outbox[0]["text"].splitlines() if "reset=" in line)
    phone = make_client()
    assert phone.post("/api/auth/set-password", json={"token": link.split("reset=")[1], "password": "a-brand-new-password"}).status_code == 200
    assert eng.get("/api/auth/me").status_code == 401  # the old session ended
    assert make_client().post("/api/auth/login", json={"email": email, "password": DEMO["demo-eng"]["password"]}).status_code == 401
    assert make_client().post("/api/auth/login", json={"email": email, "password": "a-brand-new-password"}).status_code == 200


def test_without_email_forgot_password_points_to_the_coordinator(make_client):
    r = make_client().post("/api/auth/forgot", json={"email": DEMO["demo-eng"]["email"]}).json()
    assert r["email"] is False


def test_forgot_password_requests_are_limited(make_client):
    client = make_client()
    for _ in range(5):
        client.post("/api/auth/forgot", json={"email": "someone@demo-eng.example"})
    assert client.post("/api/auth/forgot", json={"email": "someone@demo-eng.example"}).status_code == 429


# ---- who can make links --------------------------------------------------------------------------------------------
def test_only_coordinators_of_the_same_college_make_links(eng, arts, hod, kumar):
    me = next(u for u in eng.get("/api/users").json()["users"] if u["you"])
    assert arts.post(f"/api/users/{me['id']}/reset-link").status_code == 404
    assert arts.post(f"/api/users/{me['id']}/invite").status_code == 404
    assert hod.post(f"/api/users/{me['id']}/reset-link").status_code == 403
    assert kumar.post(f"/api/users/{me['id']}/reset-link").status_code == 403
