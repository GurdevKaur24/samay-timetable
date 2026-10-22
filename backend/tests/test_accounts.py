"""New colleges sign up; coordinators manage their own college's accounts and passwords."""

from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME
from app.main import create_app

from .test_timetables import generate

NEW = {"college_name": "Guru Nanak Model College", "place": "Ludhiana", "name": "Ms. Kaur",
       "email": "coordinator@gnmc.example", "password": "a-strong-password"}


def test_a_new_college_signs_up_and_starts_empty(make_client):
    client = make_client()
    r = client.post("/api/auth/signup", json=NEW)
    assert r.status_code == 201 and r.json()["college"]["name"] == NEW["college_name"]
    assert COOKIE_NAME in client.cookies
    summary = client.get("/api/college").json()
    assert summary["counts"] == {k: 0 for k in ["departments", "courses", "sections", "teachers", "subjects", "rooms", "assignments"]}
    assert summary["scheme"]["days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]  # a sensible week to start from
    assert client.get("/api/precheck").json()["ready"] is True


def test_an_empty_college_can_generate_without_errors(make_client):
    client = make_client()
    client.post("/api/auth/signup", json=NEW)
    job = generate(client)
    assert job["status"] == "done"
    assert client.get("/api/timetables/latest").json()["entries"] == []


def test_new_college_is_private_from_the_demo_colleges(make_client, eng):
    client = make_client()
    client.post("/api/auth/signup", json=NEW)
    assert client.get("/api/college/data").json()["data"]["teachers"] == []
    assert eng.get("/api/college").json()["name"] == "Demo Engineering College"
    assert NEW["college_name"] not in eng.get("/api/college/data").text


def test_signup_needs_a_proper_email_and_password(make_client):
    client = make_client()
    assert client.post("/api/auth/signup", json=NEW | {"password": "short"}).status_code == 422
    assert client.post("/api/auth/signup", json=NEW | {"email": "not-an-email"}).status_code == 422
    client.post("/api/auth/signup", json=NEW)
    again = make_client().post("/api/auth/signup", json=NEW | {"college_name": "Another College"})
    assert again.status_code == 409 and "Sign in instead" in again.json()["detail"]


def test_signup_can_be_switched_off(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "closed.db", signup=False))
    assert client.post("/api/auth/signup", json=NEW).status_code == 404


# ---- managing accounts -------------------------------------------------------------------------------------
def test_add_a_coordinator_who_can_then_sign_in(eng, make_client):
    r = eng.post("/api/users", json={"name": "Mr. Gill", "email": "gill@demo-eng.example", "password": "temporary-pass"})
    assert r.status_code == 201
    people = eng.get("/api/users").json()["users"]
    assert {p["email"] for p in people} == {"coordinator@demo-eng.example", "gill@demo-eng.example"}
    assert sum(p["you"] for p in people) == 1
    other = make_client()
    signed_in = other.post("/api/auth/login", json={"email": "gill@demo-eng.example", "password": "temporary-pass"})
    assert signed_in.json()["college"]["name"] == "Demo Engineering College"


def test_users_list_shows_only_my_college(eng, arts):
    assert {p["email"] for p in arts.get("/api/users").json()["users"]} == {"coordinator@city-arts.example"}


def test_remove_a_coordinator_but_not_yourself_or_another_colleges(eng, arts):
    new_id = eng.post("/api/users", json={"name": "Mr. Gill", "email": "gill@demo-eng.example", "password": "temporary-pass"}).json()["id"]
    me = next(p["id"] for p in eng.get("/api/users").json()["users"] if p["you"])
    assert eng.delete(f"/api/users/{me}").status_code == 400
    assert arts.delete(f"/api/users/{new_id}").status_code == 404  # other college can't touch it
    assert eng.delete(f"/api/users/{new_id}").status_code == 200
    assert len(eng.get("/api/users").json()["users"]) == 1


def test_change_password_signs_out_other_devices(make_client):
    from .conftest import DEMO, sign_in
    laptop, phone = make_client(), make_client()
    sign_in(laptop, "demo-eng"), sign_in(phone, "demo-eng")
    old = DEMO["demo-eng"]["password"]
    assert laptop.post("/api/auth/password", json={"current": "wrong", "new": "another-password"}).status_code == 400
    assert laptop.post("/api/auth/password", json={"current": old, "new": old}).status_code == 400
    r = laptop.post("/api/auth/password", json={"current": old, "new": "another-password"})
    assert r.status_code == 200
    assert laptop.get("/api/auth/me").status_code == 200  # this device stays signed in
    assert phone.get("/api/auth/me").status_code == 401   # the other one is signed out
    assert sign_in(make_client(), "demo-eng").status_code == 401
    assert make_client().post("/api/auth/login", json={"email": DEMO["demo-eng"]["email"], "password": "another-password"}).status_code == 200
