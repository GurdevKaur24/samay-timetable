"""One college can never see another college's data, or learn which other colleges exist."""

import json

import pytest

PRIVATE_ENDPOINTS = ["/api/auth/me", "/api/college", "/api/college/data"]


@pytest.mark.parametrize("path", PRIVATE_ENDPOINTS)
def test_every_private_endpoint_needs_sign_in(make_client, path):
    assert make_client().get(path).status_code == 401


def test_each_college_gets_only_its_own_data(eng, arts):
    eng_data = eng.get("/api/college/data").json()["data"]
    arts_data = arts.get("/api/college/data").json()["data"]
    assert eng_data["id"] == "demo-eng" and arts_data["id"] == "city-arts"
    assert {t["name"] for t in eng_data["teachers"]}.isdisjoint({t["name"] for t in arts_data["teachers"]})


@pytest.mark.parametrize("path", PRIVATE_ENDPOINTS)
def test_no_response_mentions_the_other_college(eng, arts, path):
    eng_text, arts_text = json.dumps(eng.get(path).json()), json.dumps(arts.get(path).json())
    assert "City Arts" not in eng_text and "city-arts" not in eng_text
    assert "Demo Engineering" not in arts_text and "demo-eng" not in arts_text


@pytest.mark.parametrize("trick", ["?college_id=city-arts", "?college=city-arts", "?id=city-arts"])
def test_naming_another_college_in_the_url_is_ignored(eng, trick):
    data = eng.get("/api/college/data" + trick).json()["data"]
    assert data["id"] == "demo-eng"


def test_there_is_no_way_to_list_colleges(eng):
    for path in ["/api/colleges", "/api/college/list", "/api/admin/colleges"]:
        assert eng.get(path).status_code == 404


def test_signing_in_to_one_college_never_returns_the_other(make_client):
    from .conftest import sign_in
    client = make_client()
    sign_in(client, "city-arts")
    assert client.get("/api/college").json()["name"] == "City Arts and Science College"
    sign_in(client, "demo-eng")  # same browser, new sign-in replaces the session cookie
    assert client.get("/api/college").json()["name"] == "Demo Engineering College"


def test_seeded_data_is_valid_and_complete(eng):
    summary = eng.get("/api/college").json()
    assert summary["counts"] == {"departments": 3, "courses": 3, "sections": 5, "teachers": 16, "subjects": 24, "rooms": 9, "assignments": 43}
    assert summary["version"] == 1
