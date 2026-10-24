import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_USERS = json.loads((Path(__file__).resolve().parent.parent / "data" / "demo_users.json").read_text())["users"]
DEMO = {u["college"]: u for u in _USERS if u["role"] == "coordinator"}
TEACHERS = {u["college"]: u for u in _USERS if u["role"] == "teacher"}
HODS = {u["college"]: u for u in _USERS if u["role"] == "hod"}


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


def sign_in_teacher(client: TestClient, college_id: str):
    user = TEACHERS[college_id]
    return client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]})


@pytest.fixture
def kumar(make_client):
    """Dr. A. Kumar, a teacher at the demo engineering college."""
    client = make_client()
    assert sign_in_teacher(client, "demo-eng").status_code == 200
    return client


@pytest.fixture
def hod(make_client):
    """Dr. H. Sandhu, head of CSE at the demo engineering college."""
    client = make_client()
    user = HODS["demo-eng"]
    assert client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]}).status_code == 200
    return client


@pytest.fixture
def arts(make_client):
    client = make_client()
    assert sign_in(client, "city-arts").status_code == 200
    return client
