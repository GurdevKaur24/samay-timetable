"""Students: one shared code per college, no accounts. A code opens only that college's published timetable."""

import json

import pytest

from .test_timetables import generate


def turn_on(client) -> str:
    r = client.post("/api/student-access")
    assert r.status_code == 200
    return r.json()["code"]


def open_with(client, code):
    return client.post("/api/student/open", json={"code": code})


# ---- the coordinator's side ----------------------------------------------------------------------------------
def test_student_access_starts_off_and_a_coordinator_turns_it_on(eng):
    assert eng.get("/api/student-access").json() == {"enabled": False, "code": None, "published": False}
    code = turn_on(eng)
    assert len(code) == 9 and code[4] == "-"  # XXXX-XXXX
    assert eng.get("/api/student-access").json()["code"] == code


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_only_coordinators_manage_the_student_code(hod, kumar, method):
    assert hod.request(method, "/api/student-access").status_code == 403
    assert kumar.request(method, "/api/student-access").status_code == 403


# ---- a student's side ------------------------------------------------------------------------------------------
def test_a_student_opens_the_published_timetable_with_the_code(eng, make_client):
    code = turn_on(eng)
    phone = make_client()
    assert phone.get("/api/student/timetable").status_code == 401  # no code yet
    r = open_with(phone, code.lower().replace("-", " "))  # typed in lower case, with a space: still fine
    assert r.status_code == 200 and r.json()["college"]["name"] == "Demo Engineering College"
    assert phone.get("/api/student/timetable").json()["published"] is None  # nothing published yet
    generate(eng)
    eng.post("/api/timetables/1/publish")
    published = phone.get("/api/student/timetable").json()["published"]
    assert published["version"] == 1 and published["entries"]
    assert all(set(t) == {"id", "name", "dept"} for t in published["data"]["teachers"])  # no free times or limits


def test_a_wrong_code_reveals_nothing_and_guessing_is_blocked(eng, make_client):
    turn_on(eng)
    phone = make_client()
    r = open_with(phone, "AAAA-AAAA")
    assert r.status_code == 404 and r.json()["detail"] == "That code wasn't found. Check it with your college."
    for _ in range(9):
        open_with(phone, "BBBB-BBBB")
    assert open_with(phone, "CCCC-CCCC").status_code == 429


def test_a_new_code_or_turning_off_signs_phones_out(eng, make_client):
    old = turn_on(eng)
    phone = make_client()
    open_with(phone, old)
    new = turn_on(eng)
    assert new != old
    assert phone.get("/api/student/timetable").status_code == 401
    assert open_with(phone, old).status_code == 404
    assert open_with(phone, new).status_code == 200
    eng.delete("/api/student-access")
    assert phone.get("/api/student/timetable").status_code == 401
    assert open_with(make_client(), new).status_code == 404


def test_leaving_forgets_the_college(eng, make_client):
    phone = make_client()
    open_with(phone, turn_on(eng))
    assert phone.post("/api/student/leave").status_code == 200
    assert phone.get("/api/student/timetable").status_code == 401


# ---- privacy -------------------------------------------------------------------------------------------------
def test_a_student_sees_only_their_own_college(eng, arts, make_client):
    eng_code, arts_code = turn_on(eng), turn_on(arts)
    assert eng_code != arts_code
    generate(eng), generate(arts)
    eng.post("/api/timetables/1/publish"), arts.post("/api/timetables/1/publish")
    phone = make_client()
    open_with(phone, arts_code)
    text = json.dumps(phone.get("/api/student/timetable").json())
    assert "City Arts" in text and "Demo Engineering" not in text and "demo-eng" not in text


@pytest.mark.parametrize("path", ["/api/college", "/api/college/data", "/api/timetables", "/api/published", "/api/users", "/api/teacher", "/api/auth/me"])
def test_a_student_code_opens_nothing_else(eng, make_client, path):
    phone = make_client()
    open_with(phone, turn_on(eng))
    assert phone.get(path).status_code == 401
