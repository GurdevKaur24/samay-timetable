import copy

from .test_timetables import generate


def load(client):
    body = client.get("/api/college/data").json()
    return body["version"], body["data"]


def test_saving_data_bumps_the_version(eng):
    version, data = load(eng)
    data["rooms"][0]["capacity"] = 75
    r = eng.put("/api/college/data", json={"version": version, "data": data})
    assert r.status_code == 200 and r.json()["version"] == version + 1
    assert load(eng)[1]["rooms"][0]["capacity"] == 75


def test_two_people_cannot_overwrite_each_other(make_client):
    from .conftest import sign_in
    first, second = make_client(), make_client()
    sign_in(first, "demo-eng"), sign_in(second, "demo-eng")
    version, data = load(first)
    _, data2 = load(second)
    assert first.put("/api/college/data", json={"version": version, "data": data}).status_code == 200
    r = second.put("/api/college/data", json={"version": version, "data": data2})  # started from the old version
    assert r.status_code == 409 and "Reload" in r.json()["detail"]


def test_bad_data_is_refused_with_plain_reasons_and_nothing_changes(eng):
    version, data = load(eng)
    data["sections"][0]["course"] = "NO-SUCH-COURSE"
    r = eng.put("/api/college/data", json={"version": version, "data": data})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["message"] == "Your changes weren't saved."
    assert any("unknown course" in p for p in detail["problems"])
    assert load(eng)[0] == version


def test_saving_can_never_touch_another_college(eng, arts):
    version, data = load(eng)
    data["id"] = "city-arts"  # trying to write into the other college
    data["name"] = "Hijacked"
    assert eng.put("/api/college/data", json={"version": version, "data": data}).status_code == 200
    assert arts.get("/api/college").json()["name"] == "City Arts and Science College"
    assert load(eng)[1]["id"] == "demo-eng"  # saved into the signed-in user's own college only


def test_saving_needs_sign_in(make_client):
    assert make_client().put("/api/college/data", json={"version": 1, "data": {}}).status_code == 401


# ---- edited timetables (assistant changes) ------------------------------------------------------------------
def free_slot_move(t):
    """Move one lecture to a slot where its section, teacher and a suitable room are all free."""
    data, entries = t["data"], t["entries"]
    a_by_id = {a["id"]: a for a in data["assignments"]}
    lab = {s["id"] for s in data["subjects"] if s["kind"] == "lab"}
    section_of = lambda g: g.split("/")[0]  # noqa: E731
    for i, e in enumerate(entries):
        a = a_by_id[e["assignment"]]
        if a["subject"] in lab:
            continue
        for day in data["scheme"]["days"]:
            if any(o["assignment"] == e["assignment"] and o["day"] == day for o in entries):
                continue
            for p in range(1, len(data["scheme"]["periods"]) + 1):
                busy = [o for o in entries if o["day"] == day and o["period"] == p]
                if any(section_of(a_by_id[o["assignment"]]["group"]) == a["group"] or a_by_id[o["assignment"]]["teacher"] == a["teacher"] for o in busy):
                    continue
                if any(o["room"] == e["room"] for o in busy):
                    continue
                moved = copy.deepcopy(entries)
                moved[i].update(day=day, period=p)
                return moved
    raise AssertionError("no free slot found")


def test_an_approved_change_is_saved_as_a_new_version(eng):
    generate(eng)
    t = eng.get("/api/timetables/latest").json()
    r = eng.post("/api/timetables/1/revise", json={"entries": free_slot_move(t)})
    assert r.status_code == 201 and r.json()["version"] == 2
    v2 = eng.get("/api/timetables/2").json()
    assert v2["solver_status"] == "edited" and v2["edited_from"] == 1
    assert eng.post("/api/timetables/2/check").json()["clashes"] == 0


def test_a_change_that_causes_a_clash_is_refused(eng):
    generate(eng)
    t = eng.get("/api/timetables/latest").json()
    entries = copy.deepcopy(t["entries"])
    entries[1].update(day=entries[0]["day"], period=entries[0]["period"], room=entries[0]["room"])
    r = eng.post("/api/timetables/1/revise", json={"entries": entries})
    assert r.status_code == 422 and r.json()["detail"]["problems"]
    assert eng.get("/api/timetables/latest").json()["version"] == 1


def test_editing_an_out_of_date_timetable_is_refused(eng):
    generate(eng)
    t = eng.get("/api/timetables/latest").json()
    version, data = load(eng)
    data["rooms"][0]["capacity"] += 1  # a change that affects scheduling
    eng.put("/api/college/data", json={"version": version, "data": data})
    r = eng.post("/api/timetables/1/revise", json={"entries": t["entries"]})
    assert r.status_code == 409 and "Generate again" in r.json()["detail"]


def test_changes_that_do_not_affect_scheduling_keep_the_timetable_current(eng):
    generate(eng)
    version, data = load(eng)
    data["departments"][0].update(status="review", hod="Dr. New Head", name="Computer Science")
    data["name"] = "Demo Engineering College (renamed)"
    assert eng.put("/api/college/data", json={"version": version, "data": data}).status_code == 200
    assert eng.get("/api/timetables/latest").json()["out_of_date"] is False
    assert eng.get("/api/timetables").json()["timetables"][0]["out_of_date"] is False


def test_other_college_cannot_edit_my_timetable(eng, arts):
    generate(eng)
    t = eng.get("/api/timetables/latest").json()
    assert arts.post("/api/timetables/1/revise", json={"entries": t["entries"]}).status_code == 404
