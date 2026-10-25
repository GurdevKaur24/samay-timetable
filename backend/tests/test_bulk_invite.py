"""One click invites every teacher who has an email and no account yet. Emails don't affect the timetable."""

import pytest
from pydantic import ValidationError

from app.schema import CollegeData
from solver.college import load_college

from .test_timetables import generate


def with_emails(eng, emails: dict[str, str]):
    body = eng.get("/api/college/data").json()
    for t in body["data"]["teachers"]:
        if t["id"] in emails:
            t["email"] = emails[t["id"]]
    r = eng.put("/api/college/data", json={"version": body["version"], "data": body["data"]})
    assert r.status_code == 200, r.json()


def test_invite_all_teachers_with_an_email(eng, make_client):
    with_emails(eng, {"T02": "s.kaur@demo-eng.example", "T03": "r.sharma@demo-eng.example", "T01": "a.kumar@demo-eng.example"})
    r = eng.post("/api/users/invite-teachers").json()
    assert sorted(i["name"] for i in r["invited"]) == ["Dr. R. Sharma", "Prof. S. Kaur"]
    reasons = {s["name"]: s["reason"] for s in r["skipped"]}
    assert reasons["Dr. A. Kumar"] == "already has an account"  # the demo teacher account
    assert sum(1 for v in reasons.values() if v == "no email") == 13
    link = next(i["link"] for i in r["invited"] if i["name"] == "Dr. R. Sharma")
    phone = make_client()
    signed_in = phone.post("/api/auth/set-password", json={"token": link.split("=", 1)[1], "password": "sharma-password"})
    assert signed_in.status_code == 200 and phone.get("/api/teacher").json()["me"]["name"] == "Dr. R. Sharma"


def test_inviting_again_skips_people_who_already_have_an_account(eng):
    with_emails(eng, {"T02": "s.kaur@demo-eng.example"})
    eng.post("/api/users/invite-teachers")
    again = eng.post("/api/users/invite-teachers").json()
    assert again["invited"] == [] and any(s["name"] == "Prof. S. Kaur" and s["reason"] == "already has an account" for s in again["skipped"])


def test_invite_only_chosen_teachers(eng):
    with_emails(eng, {"T02": "s.kaur@demo-eng.example", "T03": "r.sharma@demo-eng.example"})
    r = eng.post("/api/users/invite-teachers", json={"teachers": ["T03"]}).json()
    assert [i["name"] for i in r["invited"]] == ["Dr. R. Sharma"]


def test_bulk_invites_are_emailed_when_email_is_set_up(app, eng):
    sent = []
    app.state.send_email = lambda to, subject, text: sent.append(to) or True
    with_emails(eng, {"T02": "s.kaur@demo-eng.example"})
    r = eng.post("/api/users/invite-teachers").json()
    assert sent == ["s.kaur@demo-eng.example"] and r["invited"][0]["emailed"] is True and "1 by email" in r["message"]


def test_an_email_already_used_by_another_account_is_skipped(eng):
    with_emails(eng, {"T02": "coordinator@demo-eng.example"})
    r = eng.post("/api/users/invite-teachers").json()
    assert any(s["name"] == "Prof. S. Kaur" and "already used" in s["reason"] for s in r["skipped"])


def test_only_coordinators_invite_and_only_their_own_teachers(eng, arts, hod, kumar):
    assert hod.post("/api/users/invite-teachers").status_code == 403
    assert kumar.post("/api/users/invite-teachers").status_code == 403
    with_emails(eng, {"T02": "s.kaur@demo-eng.example"})
    r = arts.post("/api/users/invite-teachers").json()
    assert all(i["email"] != "s.kaur@demo-eng.example" for i in r["invited"])


def test_adding_emails_keeps_the_timetable_up_to_date(eng):
    generate(eng)
    with_emails(eng, {"T02": "s.kaur@demo-eng.example"})
    assert eng.get("/api/timetables/latest").json()["out_of_date"] is False


def test_teacher_emails_must_be_valid_and_different():
    d = load_college("demo-eng")
    d["teachers"][0]["email"] = "not-an-email"
    with pytest.raises(ValidationError):
        CollegeData.model_validate(d)
    d["teachers"][0]["email"] = d["teachers"][1]["email"] = "same@demo-eng.example"
    with pytest.raises(ValidationError) as err:
        CollegeData.model_validate(d)
    assert "same email" in str(err.value)
