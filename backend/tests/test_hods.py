"""Heads of department: they manage only their own department's data (and may give its classes to any teacher),
see the published timetable, and can't generate, publish or manage accounts. Colleges stay apart."""

import json

import pytest

from .test_timetables import generate


def load(client):
    body = client.get("/api/college/data").json()
    return body["version"], body["data"]


def save(client, version, data):
    return client.put("/api/college/data", json={"version": version, "data": data})


def problems_of(r):
    return " ".join(r.json()["detail"]["problems"])


# ---- what a head of department may do ------------------------------------------------------------------------
def test_a_head_of_department_signs_in(hod):
    me = hod.get("/api/auth/me").json()["user"]
    assert me["role"] == "hod" and me["dept"] == "CSE" and me["role_label"] == "Head of department"
    assert hod.get("/api/college").json()["name"] == "Demo Engineering College"
    assert load(hod)[1]["id"] == "demo-eng"


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/precheck"), ("POST", "/api/timetables"), ("GET", "/api/timetables"), ("GET", "/api/timetables/latest"),
    ("POST", "/api/timetables/1/publish"), ("DELETE", "/api/published"), ("GET", "/api/users"), ("GET", "/api/teacher"),
])
def test_a_head_of_department_cannot_generate_publish_or_manage_accounts(hod, method, path):
    assert hod.request(method, path).status_code == 403


def test_hod_changes_their_own_department(hod, eng):
    version, data = load(hod)
    data["teachers"].append({"id": "T99", "name": "Dr. New Teacher", "dept": "CSE", "unavailable": [["Tue", 1]]})
    next(s for s in data["sections"] if s["id"] == "CSE-3A")["strength"] = 58
    next(d for d in data["departments"] if d["id"] == "CSE").update(status="review", hod="Dr. H. Sandhu")
    data["courses"].append({"id": "MTECH-CSE", "name": "M.Tech CSE", "dept": "CSE", "years": 2})
    r = save(hod, version, data)
    assert r.status_code == 200, r.json()
    saved = load(eng)[1]
    assert any(t["id"] == "T99" for t in saved["teachers"])
    assert next(d for d in saved["departments"] if d["id"] == "CSE")["status"] == "review"


def test_hod_can_give_their_sections_classes_to_another_departments_teacher(hod):
    version, data = load(hod)
    ece_teacher = next(t["id"] for t in data["teachers"] if t["dept"] == "ECE")
    data["assignments"].append({"id": "A99", "subject": "CS301", "group": "CSE-5A", "teacher": ece_teacher, "periods": 1})
    data["assignments"] = [a for a in data["assignments"] if not (a["group"] == "CSE-3B" and a["subject"] == "CS303")]
    assert save(hod, version, data).status_code == 200


@pytest.mark.parametrize("change,expect", [
    (lambda d: d["rooms"][0].update(capacity=999), "Rooms can only be changed"),
    (lambda d: d["scheme"]["rules"].update(lectures_per_week=5), "college week"),
    (lambda d: d.update(name="Renamed College"), "college name"),
    (lambda d: next(t for t in d["teachers"] if t["dept"] == "ECE").update(max_per_day=1), "Teacher"),
    (lambda d: next(s for s in d["sections"] if s["dept"] == "ECE").update(strength=10), "Section"),
    (lambda d: d["teachers"].append({"id": "T98", "name": "Someone", "dept": "ECE"}), "Teacher T98"),
    (lambda d: next(t for t in d["teachers"] if t["dept"] == "CSE").update(dept="ECE"), "Teacher"),
    (lambda d: next(d_ for d_ in d["departments"] if d_["id"] == "ECE").update(status="review"), "Electronics"),
    (lambda d: next(d_ for d_ in d["departments"] if d_["id"] == "CSE").update(name="Computing"), "Ask the timetable coordinator"),
    (lambda d: d["assignments"].pop(next(i for i, a in enumerate(d["assignments"]) if a["group"].startswith("ECE"))), "other departments' sections"),
    (lambda d: next(s for s in d["subjects"] if s["dept"] == "AS").update(name="Maths"), "Subject"),
])
def test_hod_cannot_change_anything_outside_their_department(hod, eng, change, expect):
    version, data = load(hod)
    before = load(eng)[1]
    change(data)
    r = save(hod, version, data)
    assert r.status_code == 403 and expect in problems_of(r), r.json()
    assert r.json()["detail"]["message"] == "Your changes weren't saved."
    assert load(eng) == (version, before)  # nothing changed


def test_coordinators_are_not_limited_to_one_department(eng):
    version, data = load(eng)
    next(s for s in data["sections"] if s["dept"] == "ECE")["strength"] = 50
    data["rooms"][0]["capacity"] = 80
    assert save(eng, version, data).status_code == 200


# ---- the published timetable --------------------------------------------------------------------------------
def test_hods_and_teachers_see_the_published_timetable(eng, hod, kumar):
    assert hod.get("/api/published").status_code == 404
    generate(eng)
    eng.post("/api/timetables/1/publish")
    published = hod.get("/api/published").json()
    assert published["version"] == 1 and published["entries"]
    assert all(set(t) == {"id", "name", "dept"} for t in published["data"]["teachers"])
    assert kumar.get("/api/published").json()["version"] == 1


def test_the_published_timetable_needs_sign_in(make_client):
    assert make_client().get("/api/published").status_code == 401


# ---- HOD accounts --------------------------------------------------------------------------------------------
def test_a_coordinator_adds_a_head_of_department(eng, make_client):
    new = {"name": "Dr. B. Gill", "email": "hod.ece@demo-eng.example", "password": "temporary-pass", "role": "hod"}
    assert eng.post("/api/users", json=new).status_code == 422
    assert eng.post("/api/users", json=new | {"dept": "NOPE"}).status_code == 422
    assert eng.post("/api/users", json=new | {"dept": "ECE"}).status_code == 201
    listed = next(u for u in eng.get("/api/users").json()["users"] if u["email"] == new["email"])
    assert listed["role"] == "hod" and listed["dept"] == "ECE"
    gill = make_client()
    gill.post("/api/auth/login", json={"email": new["email"], "password": new["password"]})
    version, data = load(gill)
    next(s for s in data["sections"] if s["dept"] == "ECE")["strength"] = 50
    assert save(gill, version, data).status_code == 200
    version, data = load(gill)
    next(s for s in data["sections"] if s["dept"] == "CSE")["strength"] = 50
    assert save(gill, version, data).status_code == 403


# ---- colleges stay apart -------------------------------------------------------------------------------------
def test_a_head_of_department_only_ever_sees_their_own_college(eng, arts, hod):
    generate(arts)
    arts.post("/api/timetables/1/publish")
    assert hod.get("/api/published").status_code == 404  # City Arts published, Demo Engineering hasn't
    text = json.dumps(load(hod)) + json.dumps(hod.get("/api/college").json())
    assert "City Arts" not in text and "city-arts" not in text
    version, data = load(hod)
    data["id"] = "city-arts"  # trying to write into the other college
    assert save(hod, version, data).status_code == 200
    assert load(arts)[1]["name"] == "City Arts and Science College" and load(hod)[1]["id"] == "demo-eng"
