"""Hand editing: locked classes stay put when generating again; versions can be restored and deleted."""

from solver.college import load_college
from solver.model import solve
from solver.validator import validate

from .test_timetables import generate


def sessions(entries):
    """(assignment, day) -> (first period, room)"""
    out = {}
    for e in entries:
        key = (e["assignment"], e["day"])
        if key not in out or e["period"] < out[key][0]:
            out[key] = (e["period"], e["room"])
    return out


def lock_for(timetable, n=2):
    by_id = {a["id"]: a for a in timetable["data"]["assignments"]}
    locks = []
    for (aid, day), (start, room) in list(sessions(timetable["entries"]).items())[:n]:
        locks.append({"assignment": aid, "subject": by_id[aid]["subject"], "group": by_id[aid]["group"], "day": day, "start": start, "room": room})
    return locks


# ---- the generator ------------------------------------------------------------------------------------------
def test_locked_sessions_stay_exactly_where_they_are():
    data = load_college("demo-eng")
    first = solve(data, time_limit=20)
    fixed = [{"assignment": a, "day": d, "start": s, "room": r} for (a, d), (s, r) in list(sessions(first["entries"]).items())[:6]]
    second = solve(data, time_limit=20, fixed=fixed)
    assert second["status"] in ("optimal", "feasible") and validate(data, second["entries"]) == []
    kept = sessions(second["entries"])
    assert all(kept[(f["assignment"], f["day"])] == (f["start"], f["room"]) for f in fixed)


def test_a_lock_that_cannot_hold_is_explained():
    data = load_college("demo-eng")
    kumar = next(a["id"] for a in data["assignments"] if a["teacher"] == "T01")  # Dr. A. Kumar is unavailable Mon P1–P2
    result = solve(data, time_limit=10, fixed=[{"assignment": kumar, "day": "Mon", "start": 1, "room": "LH-101"}])
    assert result["status"] == "infeasible" and "Unlock it" in result["message"]


# ---- locks through the API ----------------------------------------------------------------------------------
def test_locks_are_saved_and_kept_when_generating_again(eng):
    generate(eng)
    v1 = eng.get("/api/timetables/latest").json()
    locks = lock_for(v1, 3)
    saved = eng.put("/api/timetables/1/locks", json={"locked": locks}).json()
    assert len(saved["locked"]) == 3 and saved["version"] == 1  # locking doesn't create a version
    job = eng.post("/api/timetables", json={"locked": locks}).json()
    from .test_timetables import wait_for
    job = wait_for(eng, job)
    assert job["status"] == "done" and "3 locked class(es) stayed" in job["message"]
    v2 = eng.get("/api/timetables/latest").json()
    kept = sessions(v2["entries"])
    assert all(kept[(lk["assignment"], lk["day"])] == (lk["start"], lk["room"]) for lk in locks)
    assert len(v2["locked"]) == 3


def test_a_lock_that_does_not_match_the_class_is_ignored(eng):
    generate(eng)
    v1 = eng.get("/api/timetables/latest").json()
    lock = lock_for(v1, 1)[0] | {"subject": "SOMETHING-ELSE"}
    from .test_timetables import wait_for
    job = wait_for(eng, eng.post("/api/timetables", json={"locked": [lock]}).json())
    assert job["status"] == "done" and "no longer matched" in job["message"]


def test_locks_on_a_version_must_match_its_classes(eng):
    generate(eng)
    v1 = eng.get("/api/timetables/latest").json()
    wrong = lock_for(v1, 1)[0] | {"start": 7}
    assert eng.put("/api/timetables/1/locks", json={"locked": [wrong]}).json()["locked"] == []


# ---- history: restore and delete ---------------------------------------------------------------------------
def test_restore_makes_an_old_version_the_latest(eng):
    generate(eng)
    generate(eng)
    r = eng.post("/api/timetables/1/restore")
    assert r.status_code == 201 and r.json()["version"] == 3
    v1, v3 = eng.get("/api/timetables/1").json(), eng.get("/api/timetables/3").json()
    assert v3["entries"] == v1["entries"] and v3["restored_from"] == 1
    listed = {t["version"]: t for t in eng.get("/api/timetables").json()["timetables"]}
    assert listed[3]["how"] == "restored" and listed[3]["restored_from"] == 1


def test_restoring_a_version_built_from_older_data_is_refused(app, eng):
    generate(eng)
    data = app.state.db.get_college_data("demo-eng")
    data["rooms"][0]["capacity"] += 1
    app.state.db.save_college_data("demo-eng", data)
    r = eng.post("/api/timetables/1/restore")
    assert r.status_code == 409 and "Generate again" in r.json()["detail"]


def test_delete_a_version_and_numbers_never_repeat(eng):
    generate(eng)
    generate(eng)
    assert eng.delete("/api/timetables/2").status_code == 200
    assert [t["version"] for t in eng.get("/api/timetables").json()["timetables"]] == [1]
    assert eng.get("/api/timetables/latest").json()["version"] == 1
    assert generate(eng)["timetable_version"] == 3  # v2 is never reused
    assert eng.delete("/api/timetables/99").status_code == 404


def test_other_college_cannot_lock_restore_or_delete(eng, arts):
    generate(eng)
    v1 = eng.get("/api/timetables/latest").json()
    assert arts.put("/api/timetables/1/locks", json={"locked": lock_for(v1, 1)}).status_code == 404
    assert arts.post("/api/timetables/1/restore").status_code == 404
    assert arts.delete("/api/timetables/1").status_code == 404
    assert eng.get("/api/timetables/latest").json()["version"] == 1
