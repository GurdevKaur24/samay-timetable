def test_health(make_client):
    response = make_client().get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "samay", "demo_login": True}


def test_web_page_is_served_from_the_same_server(make_client):
    r = make_client().get("/")
    assert r.status_code == 200 and "Samay" in r.text
    assert make_client().get("/tailwind.css").status_code == 200
