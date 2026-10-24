"""Publishing a timetable, and teacher accounts: teachers see the published timetable and set when they can't teach,
but can't see or change anything else, and never anything from another college."""

import json

import pytest

from .conftest import sign_in_teacher
from .test_timetables import generate

COORDINATOR_ONLY = [
    ("GET", "/api/college"), ("GET", "/api/college/data"), ("PUT", "/api/college/data"), ("GET", "/api/precheck"),
    ("POST", "/api/timetables"), ("GET", "/api/timetables"), ("GET", "/api/timetables/latest"), ("GET", "/api/timetables/1"),
    ("POST", "/api/timetables/1/publish"), ("DELETE", "/api/published"), ("POST", "/api/timetables/1/revise"),
    ("POST", "/api/timetables/1/restore"), ("DELETE", "/api/timetables/1"), ("GET", "/api/users"), ("POST", "/api/users"),
]


# ---- what each role may do ---------------------------------------------------------------------------------
@pytest.mark.parametrize("method,path", COORDINATOR_ONLY)
def test_teachers_cannot_use_coordinator_pages(kumar, method, path):
    body = {"version": 1, "data": {}} if method == "PUT" else {"entries": [], "name": "x", "email": "x@y.zz", "password": "12345678"}
    r = kumar.request(method, path, json=body if method in ("PUT", "POST") else None)
    assert r.status_code == 403 and r.json()["detail"] == "Only timetable coordinators can do that."


def test_coordinators_do_not_get_the_teacher_pages(eng):
    assert eng.get("/api/teacher").status_code == 403
    assert eng.put("/api/teacher/unavailable", json={"unavailable": []}).status_code == 403


def test_teacher_pages_need_sign_in(make_client):
    assert make_client().get("/api/teacher").status_code == 401


def test_a_teacher_signs_in_and_sees_their_own_record(kumar):
    me = kumar.get("/api/auth/me").json()["user"]
    assert me["role"] == "teacher" and me["role_label"] == "Teacher" and me["teacher"] == "T01"
    home = kumar.get("/api/teacher").json()
    assert home["me"]["name"] == "Dr. A. Kumar" and home["me"]["unavailable"] == [["Mon", 1], ["Mon", 2]]
    assert home["scheme"]["days"][0] == "Mon"
    assert home["published"] is None  # nothing published yet


# ---- publishing ---------------------------------------------------------------------------------------------
def test_publish_shows_the_timetable_to_teachers_without_private_details(eng, kumar):
    generate(eng)
    r = eng.post("/api/timetables/1/publish")
    assert r.status_code == 200 and r.json()["published"]["version"] == 1
    assert eng.get("/api/timetables/latest").json()["published"]["version"] == 1
    assert eng.get("/api/timetables").json()["published"]["version"] == 1
    published = kumar.get("/api/teacher").json()["published"]
    assert published["version"] == 1 and published["entries"] == [
        {k: e[k] for k in ("assignment", "day", "period", "room")} for e in eng.get("/api/timetables/1").json()["entries"]]
    assert all(set(t) == {"id", "name", "dept"} for t in published["data"]["teachers"])  # no one's free times or limits


def test_generating_again_does_not_change_what_teachers_see(eng, kumar):
    generate(eng)
    eng.post("/api/timetables/1/publish")
    generate(eng)
    assert kumar.get("/api/teacher").json()["published"]["version"] == 1
    eng.post("/api/timetables/2/publish")
    assert kumar.get("/api/teacher").json()["published"]["version"] == 2


def test_only_an_up_to_date_version_can_be_published(app, eng):
    generate(eng)
    data = app.state.db.get_college_data("demo-eng")
    data["rooms"][0]["capacity"] += 1
    app.state.db.save_college_data("demo-eng", data)
    r = eng.post("/api/timetables/1/publish")
    assert r.status_code == 409 and "Generate again" in r.json()["detail"]
    assert eng.post("/api/timetables/9/publish").status_code == 404


def test_unpublish_and_the_published_version_cannot_be_deleted(eng, kumar):
    generate(eng)
    eng.post("/api/timetables/1/publish")
    r = eng.delete("/api/timetables/1")
    assert r.status_code == 409 and "Publish another version first" in r.json()["detail"]
    assert eng.delete("/api/published").status_code == 200
    assert kumar.get("/api/teacher").json()["published"] is None
    assert eng.delete("/api/timetables/1").status_code == 200


# ---- a teacher's free times ---------------------------------------------------------------------------------
def test_a_teacher_sets_when_they_cannot_teach(eng, kumar):
    generate(eng)
    r = kumar.put("/api/teacher/unavailable", json={"unavailable": [["Fri", 7], ["Fri", 6], ["Fri", 7]]})
    assert r.status_code == 200 and r.json()["unavailable"] == [["Fri", 6], ["Fri", 7]]
    me = next(t for t in eng.get("/api/college/data").json()["data"]["teachers"] if t["id"] == "T01")
    assert me["unavailable"] == [["Fri", 6], ["Fri", 7]]
    assert eng.get("/api/timetables/latest").json()["out_of_date"] is True  # the coordinator generates again
    others = [t for t in eng.get("/api/college/data").json()["data"]["teachers"] if t["id"] != "T01"]
    assert any(t.get("unavailable") for t in others)  # nobody else's free times were touched


def test_a_teacher_is_told_when_new_free_times_clash_with_the_published_timetable(eng, kumar):
    generate(eng)
    eng.post("/api/timetables/1/publish")
    t = eng.get("/api/timetables/1").json()
    mine = {a["id"] for a in t["data"]["assignments"] if a["teacher"] == "T01"}
    busy = next([e["day"], e["period"]] for e in t["entries"] if e["assignment"] in mine)
    r = kumar.put("/api/teacher/unavailable", json={"unavailable": [busy]}).json()
    assert r["clashes_with_published"] == [busy] and "generates and publishes again" in r["message"]


def test_free_times_must_be_in_the_college_week(kumar):
    assert kumar.put("/api/teacher/unavailable", json={"unavailable": [["Sun", 1]]}).status_code == 422
    assert kumar.put("/api/teacher/unavailable", json={"unavailable": [["Mon", 99]]}).status_code == 422
    assert kumar.get("/api/teacher").json()["me"]["unavailable"] == [["Mon", 1], ["Mon", 2]]


def test_a_teacher_whose_record_was_removed_is_told_plainly(app, kumar):
    data = app.state.db.get_college_data("demo-eng")
    data["teachers"] = [t for t in data["teachers"] if t["id"] != "T01"]
    app.state.db.save_college_data("demo-eng", data)
    r = kumar.get("/api/teacher")
    assert r.status_code == 404 and "coordinator" in r.json()["detail"]


# ---- teacher accounts ---------------------------------------------------------------------------------------
def test_a_coordinator_adds_a_teacher_account(eng, make_client):
    new = {"name": "Prof. S. Kaur", "email": "s.kaur@demo-eng.example", "password": "temporary-pass", "role": "teacher"}
    assert eng.post("/api/users", json=new).status_code == 422  # which teacher?
    assert eng.post("/api/users", json=new | {"teacher": "NOPE"}).status_code == 422
    assert eng.post("/api/users", json=new | {"teacher": "T01"}).status_code == 409  # Dr. Kumar already has one
    assert eng.post("/api/users", json=new | {"teacher": "T02"}).status_code == 201
    listed = next(u for u in eng.get("/api/users").json()["users"] if u["email"] == new["email"])
    assert listed["role"] == "teacher" and listed["teacher"] == "T02" and listed["role_label"] == "Teacher"
    kaur = make_client()
    kaur.post("/api/auth/login", json={"email": new["email"], "password": new["password"]})
    assert kaur.get("/api/teacher").json()["me"]["name"] == "Prof. S. Kaur"


def test_a_teacher_account_is_only_for_a_teacher_of_the_same_college(eng):
    r = eng.post("/api/users", json={"name": "X", "email": "x@demo-eng.example", "password": "temporary-pass", "role": "teacher", "teacher": "C2"})
    assert r.status_code == 422  # C2 is a City Arts teacher


# ---- colleges stay apart ------------------------------------------------------------------------------------
def test_teachers_only_ever_see_their_own_college(eng, arts, kumar, make_client):
    generate(eng)
    generate(arts)
    eng.post("/api/timetables/1/publish")
    arts.post("/api/timetables/1/publish")
    mehta = make_client()
    assert sign_in_teacher(mehta, "city-arts").status_code == 200
    kumar_text, mehta_text = json.dumps(kumar.get("/api/teacher").json()), json.dumps(mehta.get("/api/teacher").json())
    assert "City Arts" not in kumar_text and "city-arts" not in kumar_text and "Mehta" not in kumar_text
    assert "Demo Engineering" not in mehta_text and "demo-eng" not in mehta_text and "Kumar" not in mehta_text
    mehta.put("/api/teacher/unavailable", json={"unavailable": [["Mon", 3]]})
    assert kumar.get("/api/teacher").json()["me"]["unavailable"] == [["Mon", 1], ["Mon", 2]]


def test_one_college_cannot_publish_or_unpublish_another_colleges_timetable(eng, arts, kumar):
    generate(eng)
    eng.post("/api/timetables/1/publish")
    assert arts.delete("/api/published").status_code == 200  # only clears City Arts' own
    assert kumar.get("/api/teacher").json()["published"]["version"] == 1
