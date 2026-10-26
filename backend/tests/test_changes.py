"""Changing the published timetable: one week only or from now on, moves and one-day cancels; who may change what;
undo; and changes kept (or dropped) when a new version is published."""

import datetime as dt

import pytest

from app.services import changes
from app.services.change_store import plain

from .test_timetables import generate


@pytest.fixture
def published(app, eng):
    """Demo Engineering with timetable v1 published."""
    generate(eng)
    assert eng.post("/api/timetables/1/publish").status_code == 200
    return app.state.db.get_timetable("demo-eng", 1)


def next_week(base: dict) -> dict[str, str]:
    """Next week's dates (always in the future, whatever day the tests run)."""
    start = changes.week_start(changes.today("Asia/Kolkata")) + dt.timedelta(days=7)
    return changes.week_dates(base["data"]["scheme"]["days"], start)


def first_session(base: dict, *, teacher: str | None = None, dept: str | None = None, not_teacher: str | None = None) -> tuple[str, str, int]:
    """(class id, day, first period) of a lecture matching the filters."""
    data = base["data"]
    teachers = {a["id"]: a["teacher"] for a in data["assignments"]}
    depts = {s["id"]: s["dept"] for s in data["sections"]}
    from solver.college import build
    c = build(data)
    for e in sorted(base["entries"], key=lambda e: (e["day"], e["period"])):
        aid = e["assignment"]
        if c.block(aid) != 1 or (teacher and teachers[aid] != teacher) or (not_teacher and teachers[aid] == not_teacher):
            continue
        if dept and not all(depts.get(s) == dept for s in c.sections_of(aid)):
            continue
        return aid, e["day"], e["period"]
    raise AssertionError("no matching class")


def free_time(app, base, aid, day, start, scope="once", week_changes=()):
    current = app.state.db.get_college_data("demo-eng")
    slots = changes.suggest(plain(base["entries"]), base["data"], current, list(week_changes), assignment=aid, day=day, start=start, scope=scope)
    assert slots, "expected a free time"
    return slots[0]


def move(client, base, aid, day, start, slot, scope="once"):
    dates = next_week(base)
    body = {"action": "move", "scope": scope, "assignment": aid, "date": dates[day], "from_start": start,
            "to_date": dates[slot["day"]], "to_start": slot["start"], "to_room": slot["room"]}
    return client.post("/api/changes", json=body)


def week_entries(client, base, path="/api/published"):
    week = client.get(path, params={"week": next_week(base)[base["data"]["scheme"]["days"][0]]}).json()
    return (week["published"] if "published" in week else week)["week"]


# ---- one week only ---------------------------------------------------------------------------------------------
def test_a_teacher_moves_their_own_class_for_one_week(app, published, kumar):
    aid, day, start = first_session(published, teacher="T01")
    slot = free_time(app, published, aid, day, start)
    r = move(kumar, published, aid, day, start, slot)
    assert r.status_code == 201, r.json()
    assert "usual timetable comes back" in r.json()["message"]
    week = week_entries(kumar, published)
    moved = [e for e in week["entries"] if e.get("moved_from")]
    assert moved and moved[0]["day"] == slot["day"] and moved[0]["period"] == slot["start"]
    # the usual timetable (and this week) are unchanged: no new version
    usual = kumar.get("/api/published").json()
    assert usual["version"] == 1 and any(e["assignment"] == aid and e["day"] == day and e["period"] == start for e in usual["entries"])
    assert not any(e.get("moved_from") for e in usual["week"]["entries"])


def test_a_teacher_cant_change_someone_elses_class(app, published, kumar):
    aid, day, start = first_session(published, not_teacher="T01")
    slot = free_time(app, published, aid, day, start)
    r = move(kumar, published, aid, day, start, slot)
    assert r.status_code == 422 and "only change your own classes" in r.json()["detail"]["message"]


def test_a_head_of_department_changes_only_their_departments_classes(app, published, hod):
    aid, day, start = first_session(published, dept="CSE")
    assert move(hod, published, aid, day, start, free_time(app, published, aid, day, start)).status_code == 201
    aid, day, start = first_session(published, dept="ECE")
    r = move(hod, published, aid, day, start, free_time(app, published, aid, day, start))
    assert r.status_code == 422 and "own department" in r.json()["detail"]["message"]


def test_a_move_that_causes_a_clash_is_refused(published, kumar):
    aid, day, start = first_session(published, teacher="T01")
    data = published["data"]
    group = next(a["group"] for a in data["assignments"] if a["id"] == aid)
    other = next(e for e in published["entries"] if e["assignment"] != aid
                 and next(a["group"] for a in data["assignments"] if a["id"] == e["assignment"]) == group and e["day"] != day)
    slot = {"day": other["day"], "start": other["period"], "room": other["room"]}
    r = move(kumar, published, aid, day, start, slot)
    assert r.status_code == 422 and r.json()["detail"]["problems"]


def test_cancel_for_one_day_but_never_for_ever(published, kumar, make_client):
    aid, day, start = first_session(published, teacher="T01")
    date = next_week(published)[day]
    r = kumar.post("/api/changes", json={"action": "cancel", "assignment": aid, "date": date, "from_start": start})
    assert r.status_code == 201
    assert any(e.get("cancelled") for e in week_entries(kumar, published)["entries"])
    r = kumar.post("/api/changes", json={"action": "cancel", "scope": "always", "assignment": aid, "date": date, "from_start": start})
    assert r.status_code == 422 and "one day" in r.json()["detail"]["message"]


def test_past_dates_and_other_weeks_are_refused(app, published, kumar):
    aid, day, start = first_session(published, teacher="T01")
    past = (changes.week_start(changes.today("Asia/Kolkata")) - dt.timedelta(days=7)).isoformat()
    r = kumar.post("/api/changes", json={"action": "cancel", "assignment": aid, "date": past, "from_start": start})
    assert r.status_code == 422
    slot = free_time(app, published, aid, day, start)
    dates = next_week(published)
    far = (dt.date.fromisoformat(dates[slot["day"]]) + dt.timedelta(days=7)).isoformat()
    r = kumar.post("/api/changes", json={"action": "move", "assignment": aid, "date": dates[day], "from_start": start,
                                         "to_date": far, "to_start": slot["start"], "to_room": slot["room"]})
    assert r.status_code == 422 and "same week" in r.json()["detail"]["message"]


def test_students_see_changes_but_cant_make_them(app, published, kumar, eng, make_client):
    aid, day, start = first_session(published, teacher="T01")
    move(kumar, published, aid, day, start, free_time(app, published, aid, day, start))
    eng.post("/api/student-access")
    code = eng.get("/api/student-access").json()["code"]
    phone = make_client()
    assert phone.post("/api/student/open", json={"code": code}).status_code == 200
    week = week_entries(phone, published, "/api/student/timetable")
    assert any(e.get("moved_from") for e in week["entries"]) and "made_by_name" not in week["changes"][0]
    assert phone.post("/api/changes", json={"action": "cancel", "assignment": aid, "date": "2030-01-01", "from_start": 1}).status_code == 401


# ---- from now on -------------------------------------------------------------------------------------------------
def test_a_change_from_now_on_is_published_as_a_new_locked_version(app, published, kumar, eng):
    aid, day, start = first_session(published, teacher="T01")
    slot = free_time(app, published, aid, day, start, scope="always")
    r = move(kumar, published, aid, day, start, slot, scope="always")
    assert r.status_code == 201, r.json()
    v = r.json()["version"]
    assert kumar.get("/api/published").json()["version"] == v
    latest = eng.get("/api/timetables/latest").json()
    assert latest["version"] == v and latest["out_of_date"] is False
    assert any(lk["assignment"] == aid and lk["day"] == slot["day"] and lk["start"] == slot["start"] for lk in latest["locked"])
    # the coordinator sees it and can undo it: the class goes back and that is published too
    listed = eng.get("/api/changes").json()["changes"]
    assert listed[0]["scope"] == "always" and listed[0]["made_by_name"] == "Dr. A. Kumar"
    undone = eng.delete(f"/api/changes/{listed[0]['id']}")
    assert undone.status_code == 200
    back = eng.get("/api/published").json()
    assert any(e["assignment"] == aid and e["day"] == day and e["period"] == start for e in back["entries"])


# ---- seeing and undoing changes ----------------------------------------------------------------------------------
def test_people_see_and_undo_only_their_own_changes(app, published, kumar, hod, eng):
    aid, day, start = first_session(published, teacher="T01")
    change = move(kumar, published, aid, day, start, free_time(app, published, aid, day, start)).json()["change"]
    assert [c["id"] for c in kumar.get("/api/changes").json()["changes"]] == [change["id"]]
    assert hod.get("/api/changes").json()["changes"] == []
    assert hod.delete(f"/api/changes/{change['id']}").status_code == 403
    assert [c["id"] for c in eng.get("/api/changes").json()["changes"]] == [change["id"]]
    assert kumar.delete(f"/api/changes/{change['id']}").status_code == 200
    assert not any(e.get("moved_from") for e in week_entries(kumar, published)["entries"])


def test_colleges_never_see_or_undo_each_others_changes(app, published, kumar, arts):
    aid, day, start = first_session(published, teacher="T01")
    change = move(kumar, published, aid, day, start, free_time(app, published, aid, day, start)).json()["change"]
    assert arts.get("/api/changes").json()["changes"] == []
    assert arts.delete(f"/api/changes/{change['id']}").status_code == 404


def test_one_week_changes_move_to_a_newly_published_version_when_they_still_fit(app, published, kumar, eng):
    aid, day, start = first_session(published, teacher="T01")
    move(kumar, published, aid, day, start, free_time(app, published, aid, day, start))
    entries = eng.get("/api/timetables/1").json()["entries"]
    assert eng.post("/api/timetables/1/revise", json={"entries": entries}).status_code == 201  # v2: the same classes
    assert eng.post("/api/timetables/2/publish").status_code == 200
    assert any(e.get("moved_from") for e in week_entries(kumar, published)["entries"])
    assert app.state.db.list_changes("demo-eng", "2000-01-01", 0)[0]["version"] == 2


def test_nothing_can_change_before_anything_is_published(eng, kumar):
    r = kumar.post("/api/changes", json={"action": "cancel", "assignment": "A01", "date": "2030-01-07", "from_start": 1})
    assert r.status_code == 404


# ---- the pure rules ------------------------------------------------------------------------------------------------
def test_week_dates_follow_the_colleges_days():
    monday = dt.date(2026, 10, 26)
    assert changes.week_dates(["Mon", "Tue", "Sat"], monday) == {"Mon": "2026-10-26", "Tue": "2026-10-27", "Sat": "2026-10-31"}
    assert changes.day_of(["Mon", "Tue"], dt.date(2026, 10, 27)) == "Tue" and changes.day_of(["Mon"], dt.date(2026, 11, 1)) is None


def test_apply_skips_changes_that_no_longer_match():
    entries = [{"assignment": "A", "day": "Mon", "period": 1, "room": "R"}]
    ch = {"id": 1, "kind": "move", "assignment": "A", "from_day": "Tue", "from_start": 1, "to_day": "Wed", "to_start": 2, "to_room": "R"}
    assert changes.apply(entries, [ch]) == entries
