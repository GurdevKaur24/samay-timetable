def test_health(make_client):
    response = make_client().get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "samay", "api": 2, "demo_login": True, "signup": True, "assistant": False, "email": False}


def test_web_page_is_served_from_the_same_server(make_client):
    r = make_client().get("/")
    assert r.status_code == 200 and "Samay" in r.text
    assert r.headers["cache-control"] == "no-cache"  # updates show without a hard refresh
    assert make_client().get("/tailwind.css").status_code == 200


def test_the_page_and_the_server_agree_on_the_api_version():
    """The page warns when the server is older than it (e.g. not restarted after an update)."""
    import re
    from pathlib import Path

    from app.main import API_VERSION
    page = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text(encoding="utf-8")
    assert int(re.search(r"const API_VERSION = (\d+);", page).group(1)) == API_VERSION
