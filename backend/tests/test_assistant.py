"""The AI assistant's tools and endpoint. Claude itself is replaced by a stand-in, so these tests never call the API:
they prove the tools only see one college, every proposal passes the clash checker, and nothing is saved until the
coordinator applies the proposal through the normal revise endpoint."""

import copy
import json

import pytest

from app.services.assistant import clean_history, make_tools
from app.services.assistant_tools import SchedulingTools
from solver.college import load_college
from solver.model import solve
from solver.validator import validate

from .test_timetables import generate


@pytest.fixture(scope="module")
def solved():
    data = load_college("demo-eng")
    result = solve(data, time_limit=20)
    assert result["status"] in ("optimal", "feasible")
    return data, {"version": 1, "data": copy.deepcopy(data), "entries": result["entries"]}


def first_session(st):
    e = st.entries[0]
    return e["assignment"], e["day"]


# ---- the tools ----------------------------------------------------------------------------------------------
def test_tools_explain_when_there_is_no_timetable():
    st = SchedulingTools(load_college("demo-eng"), None)
    assert "No timetable" in st.find_clashes()
    assert "No timetable" in st.propose_change([{"assignment": "A01", "day": "Mon", "to_day": "Tue", "to_start": 1, "to_room": "LH-101"}], "x")
    assert st.proposal is None
    assert json.loads(st.overview())["sections"]  # the college's own structure is still available


def test_tools_read_the_timetable(solved):
    data, timetable = solved
    st = SchedulingTools(data, timetable)
    assert json.loads(st.find_clashes())["clashes"] == 0
    classes = json.loads(st.show_timetable("section", "CSE-3A"))["classes"]
    assert classes and all(c["taught_to"].startswith("CSE-3A") for c in classes)
    by_teacher = json.loads(st.show_timetable("teacher", "Dr. A. Kumar"))["classes"]
    assert by_teacher and all(c["teacher"] == "Dr. A. Kumar" for c in by_teacher)
    load = json.loads(st.teacher_load("T01"))
    assert load["periods_a_week"] == len([e for e in timetable["entries"] if e["assignment"] in {c["assignment"] for c in by_teacher}])
    assert "Mon P1" in load["cannot_teach"]
    rooms = json.loads(st.find_free_rooms("Mon", 1))["free_rooms"]
    busy = {e["room"] for e in timetable["entries"] if e["day"] == "Mon" and e["period"] == 1}
    assert rooms and not busy & {r["id"] for r in rooms}
    assert "No section" in st.show_timetable("section", "NOPE")


def test_every_free_slot_really_is_free_and_can_be_proposed(solved):
    data, timetable = solved
    st = SchedulingTools(data, timetable)
    aid, day = first_session(st)
    slots = json.loads(st.find_free_slots(aid, day))["free_slots"]
    assert slots
    for s in slots[:3]:
        out = json.loads(st.propose_change([{"assignment": aid, "day": day, "to_day": s["day"], "to_start": s["start_period"], "to_room": s["room"]}], "Move it"))
        assert out["proposed"] is True and out["clashes_after"] == 0
    applied = copy.deepcopy(timetable["entries"])
    for ch in st.proposal["changes"]:
        e = next(e for e in applied if e["assignment"] == ch["assignment"] and e["day"] == ch["from_day"] and e["period"] == ch["from_period"])
        e.update(day=ch["day"], period=ch["period"], room=ch["room"])
    assert validate(data, applied) == []


def test_a_change_that_causes_a_clash_is_never_proposed(solved):
    data, timetable = solved
    st = SchedulingTools(data, timetable)
    a, b = timetable["entries"][0], next(e for e in timetable["entries"] if e["assignment"] != timetable["entries"][0]["assignment"])
    out = json.loads(st.propose_change([{"assignment": a["assignment"], "day": a["day"], "to_day": b["day"], "to_start": b["period"], "to_room": b["room"]}], "clash"))
    assert out["proposed"] is False and out["problems"]
    assert st.proposal is None
    assert "Not proposed" in st.propose_change([{"assignment": "NOPE", "day": "Mon", "to_day": "Tue", "to_start": 1, "to_room": "LH-101"}], "x")


def test_an_out_of_date_timetable_cannot_be_changed(solved):
    data, timetable = solved
    changed = copy.deepcopy(data)
    changed["rooms"][0]["capacity"] += 1
    st = SchedulingTools(changed, timetable)
    aid, day = timetable["entries"][0]["assignment"], timetable["entries"][0]["day"]
    assert "out of date" in st.propose_change([{"assignment": aid, "day": day, "to_day": "Tue", "to_start": 1, "to_room": "LH-101"}], "x")
    assert st.proposal is None


def test_the_claude_tools_are_bound_to_one_college(solved):
    data, timetable = solved
    tools = {t.name: t for t in make_tools(SchedulingTools(data, timetable))}
    assert set(tools) == {"college_overview", "find_clashes", "show_timetable", "find_free_slots", "find_free_rooms", "teacher_load", "propose_change"}
    text = tools["college_overview"].call({})
    assert "Dr. A. Kumar" in text  # names come only from this college's data
    assert "City Arts" not in text and "Bansal" not in text


def test_conversation_history_is_tidied_for_claude():
    history = [{"role": "assistant", "content": "Hi"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"},
               {"role": "assistant", "content": "ok"}, {"role": "user", "content": "unanswered"}]
    out = clean_history(history, "new question")
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[0]["content"] == "a\n\nb" and out[-1]["content"] == "new question"


# ---- the endpoint (with a stand-in for Claude) ----------------------------------------------------------------
def stand_in(seen):
    """Behaves like the assistant asked to move the first class: finds a free slot and proposes it."""
    def chat(college_name, st, history, message):
        seen.append({"college": college_name, "data_id": st.data["id"], "history": history, "message": message})
        if st.entries:
            aid, day = first_session(st)
            slot = json.loads(st.find_free_slots(aid, day))["free_slots"][0]
            st.propose_change([{"assignment": aid, "day": day, "to_day": slot["day"], "to_start": slot["start_period"], "to_room": slot["room"]}], "Moved one class.")
        return {"reply": "Here's an option.", "proposal": st.proposal}
    return chat


def test_assistant_is_off_without_an_api_key(eng, make_client):
    assert make_client().get("/api/health").json()["assistant"] is False
    r = eng.post("/api/assistant/chat", json={"message": "hello"})
    assert r.status_code == 503 and "API key" in r.json()["detail"]


def test_only_coordinators_can_use_the_assistant(app, hod, kumar, make_client):
    app.state.assistant_chat = stand_in([])
    assert hod.post("/api/assistant/chat", json={"message": "hi"}).status_code == 403
    assert kumar.post("/api/assistant/chat", json={"message": "hi"}).status_code == 403
    assert make_client().post("/api/assistant/chat", json={"message": "hi"}).status_code == 401


def test_a_proposal_is_saved_only_when_the_coordinator_applies_it(app, eng, make_client):
    seen = []
    app.state.assistant_chat = stand_in(seen)
    assert make_client().get("/api/health").json()["assistant"] is True
    generate(eng)
    r = eng.post("/api/assistant/chat", json={"message": "Move the first class", "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello"}]})
    assert r.status_code == 200
    proposal = r.json()["proposal"]
    assert proposal and proposal["version"] == 1 and proposal["changes"]
    assert seen[0]["college"] == "Demo Engineering College" and seen[0]["data_id"] == "demo-eng"
    assert eng.get("/api/timetables/latest").json()["version"] == 1  # nothing saved yet

    t = eng.get("/api/timetables/1").json()
    entries = copy.deepcopy(t["entries"])
    for ch in proposal["changes"]:
        e = next(e for e in entries if e["assignment"] == ch["assignment"] and e["day"] == ch["from_day"] and e["period"] == ch["from_period"])
        e.update(day=ch["day"], period=ch["period"], room=ch["room"])
    applied = eng.post("/api/timetables/1/revise", json={"entries": entries})
    assert applied.status_code == 201 and applied.json()["version"] == 2


def test_the_assistant_only_sees_the_signed_in_college(app, arts):
    seen = []
    app.state.assistant_chat = stand_in(seen)
    arts.post("/api/assistant/chat", json={"message": "hi"})
    assert seen[0]["data_id"] == "city-arts" and seen[0]["college"] == "City Arts and Science College"


def test_long_or_empty_messages_are_refused(app, eng):
    app.state.assistant_chat = stand_in([])
    assert eng.post("/api/assistant/chat", json={"message": ""}).status_code == 422
    assert eng.post("/api/assistant/chat", json={"message": "x" * 5000}).status_code == 422
