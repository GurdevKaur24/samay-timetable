import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

DEMO = {u["college"]: u for u in json.loads((Path(__file__).resolve().parent.parent / "data" / "demo_users.json").read_text())["users"]}


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=tmp_path / "test.db", solve_seconds=20)


@pytest.fixture
def make_client(app):
    """A separate browser (own cookie jar) for each user, all talking to the same server and database."""
    return lambda: TestClient(app)


def sign_in(client: TestClient, college_id: str, password: str | None = None):
    user = DEMO[college_id]
    return client.post("/api/auth/login", json={"email": user["email"], "password": password or user["password"]})


@pytest.fixture
def eng(make_client):
    client = make_client()
    assert sign_in(client, "demo-eng").status_code == 200
    return client


@pytest.fixture
def arts(make_client):
    client = make_client()
    assert sign_in(client, "city-arts").status_code == 200
    return client
