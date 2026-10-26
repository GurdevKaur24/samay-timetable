"""On a public demo server the demo college is ready at start: timetable generated, checked, published, student code on."""

from app.services.demo import prepare_demos


def test_the_demo_college_is_ready_for_every_role(app, eng, kumar, make_client):
    prepare_demos(app)
    published = app.state.db.published("demo-eng")
    assert published is not None
    assert eng.post(f"/api/timetables/{published['version']}/check").json()["clashes"] == 0
    assert eng.get("/api/student-access").json()["code"] == "DEMO-2026"
    assert kumar.get("/api/teacher").json()["published"]["version"] == published["version"]
    phone = make_client()
    assert phone.post("/api/student/open", json={"code": "demo-2026"}).status_code == 200
    assert phone.get("/api/student/timetable").json()["published"]["version"] == published["version"]


def test_getting_ready_twice_changes_nothing(app):
    prepare_demos(app)
    first = app.state.db.published("demo-eng")
    prepare_demos(app)
    assert app.state.db.published("demo-eng") == first
    assert len(app.state.db.list_timetables("demo-eng")) == 1


def test_other_colleges_are_left_alone(app):
    prepare_demos(app)
    assert app.state.db.published("city-arts") is None
