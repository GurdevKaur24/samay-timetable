import time

import pytest

from solver.validator import validate


def wait_for(client, job, timeout=90):
    end = time.time() + timeout
    while job["status"] in ("queued", "running"):
        assert time.time() < end, "generation took too long"
        time.sleep(0.25)
        job = client.get(f"/api/jobs/{job['id']}").json()
    return job


def generate(client):
    r = client.post("/api/timetables")
    assert r.status_code == 202
    return wait_for(client, r.json())


# ---- pre-check ---------------------------------------------------------------------------------------------
def test_precheck_says_seed_college_is_ready(eng):
    r = eng.get("/api/precheck").json()
    assert r["ready"] is True and r["errors"] == 0
    assert any(i["level"] == "info" and "unavailable" in i["text"] for i in r["items"])


def test_precheck_finds_an_overloaded_teacher(app, eng):
    db = app.state.db
    data = db.get_college_data("demo-eng")
    data["teachers"][0]["max_per_day"] = 1  # Dr. A. Kumar: 6 periods a week, but only 1 a day and Mon P1–P2 off
    db.save_college_data("demo-eng", data)
    r = eng.get("/api/precheck").json()
    assert r["ready"] is False
    assert any("Dr. A. Kumar" in i["text"] and i["level"] == "error" for i in r["items"])


# ---- generating --------------------------------------------------------------------------------------------
def test_generate_saves_a_checked_timetable(app, eng):
    job = generate(eng)
    assert job["status"] == "done", job["message"]
    assert job["timetable_version"] == 1 and "0 clashes" in job["message"]

    t = eng.get("/api/timetables/latest").json()
    assert t["version"] == 1 and t["built_from"] == 1 and t["out_of_date"] is False
    assert validate(t["data"], t["entries"]) == []
    assert t["metrics"]["classes"] == len(t["entries"]) == 107
    assert eng.post("/api/timetables/1/check").json()["clashes"] == 0


def test_each_run_is_a_new_version(eng):
    assert generate(eng)["timetable_version"] == 1
    assert generate(eng)["timetable_version"] == 2
    versions = eng.get("/api/timetables").json()["timetables"]
    assert [v["version"] for v in versions] == [2, 1]
    assert eng.get("/api/timetables/1").json()["version"] == 1


def test_starting_twice_returns_the_running_job(eng):
    first = eng.post("/api/timetables").json()
    second = eng.post("/api/timetables").json()
    assert second["id"] == first["id"]
    wait_for(eng, first)


def test_timetable_is_marked_out_of_date_when_data_changes(app, eng):
    generate(eng)
    db = app.state.db
    data = db.get_college_data("demo-eng")
    data["rooms"][0]["capacity"] = 71
    db.save_college_data("demo-eng", data)
    t = eng.get("/api/timetables/latest").json()
    assert t["out_of_date"] is True and t["built_from"] == 1
    assert eng.get("/api/timetables").json()["data_version"] == 2


def test_impossible_data_fails_with_a_plain_message_and_saves_nothing(app, eng):
    db = app.state.db
    data = db.get_college_data("demo-eng")
    data["assignments"][0]["periods"] = 40  # more than the whole week
    db.save_college_data("demo-eng", data)
    job = generate(eng)
    assert job["status"] == "failed"
    assert "pre-check" in job["message"]
    assert eng.get("/api/timetables/latest").status_code == 404


def test_no_timetable_yet(eng):
    r = eng.get("/api/timetables/latest")
    assert r.status_code == 404 and "Generate one first" in r.json()["detail"]


def test_both_colleges_generate_on_their_own_schemes(eng, arts):
    assert generate(eng)["status"] == "done"
    assert generate(arts)["status"] == "done"
    arts_t = arts.get("/api/timetables/latest").json()
    assert {e["day"] for e in arts_t["entries"]} == {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat"}
    assert arts_t["version"] == 1  # version numbers are per college


# ---- privacy -----------------------------------------------------------------------------------------------
def test_other_college_cannot_see_a_job_or_timetable(eng, arts):
    job = generate(eng)
    assert arts.get(f"/api/jobs/{job['id']}").status_code == 404
    assert arts.get("/api/timetables/latest").status_code == 404
    assert arts.get("/api/timetables/1").status_code == 404
    assert arts.post("/api/timetables/1/check").status_code == 404
    assert arts.get("/api/timetables").json()["timetables"] == []


def test_job_status_never_reveals_the_college(eng):
    job = eng.post("/api/timetables").json()
    assert "college_id" not in job
    wait_for(eng, job)


@pytest.mark.parametrize("method,path", [("get", "/api/precheck"), ("post", "/api/timetables"), ("get", "/api/timetables"),
                                         ("get", "/api/timetables/latest"), ("get", "/api/jobs/abc")])
def test_generation_endpoints_need_sign_in(make_client, method, path):
    assert getattr(make_client(), method)(path).status_code == 401
