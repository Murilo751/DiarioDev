import json

import pytest
from werkzeug.security import generate_password_hash

import api


@pytest.fixture
def settings():
    return {
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "DATABASE_URL": "postgresql://test/db",
        "INITIAL_USERNAME": "student",
        "INITIAL_PASSWORD_HASH": generate_password_hash("correct-password"),
    }


def test_initialization_and_config_validation(monkeypatch, settings, capsys):
    calls = []
    monkeypatch.setattr(api.db, "initialize", lambda *args: calls.append(args))
    api.create_app(settings)
    assert calls[0][:3] == (
        settings["DATABASE_URL"], settings["INITIAL_USERNAME"],
        settings["INITIAL_PASSWORD_HASH"],
    )
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "initialize" and event["status"] == "success"

    with pytest.raises(RuntimeError, match="Configure"):
        api.create_app({**settings, "SECRET_KEY": ""})

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "initialize", fail)
    with pytest.raises(RuntimeError, match="db failed"):
        api.create_app(settings)
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_health_and_protected_routes(monkeypatch, settings, capsys):
    app = api.create_app(settings, initialize=False)
    client = app.test_client()
    assert client.get("/api/web/health").status_code == 200
    assert client.get("/api/web/me").status_code == 401
    assert client.post("/api/web/logout").status_code == 401
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["operation"] for event in events] == ["health", "me", "logout"]
    assert all(event["layer"] == "api" and event["client"] == "web" for event in events)


def test_login_failures(monkeypatch, settings, capsys):
    app = api.create_app(settings, initialize=False)
    client = app.test_client()
    assert client.post("/api/web/login", json={}).status_code == 401
    assert client.post("/api/web/login", json=["invalid"]).status_code == 401
    assert client.post("/api/web/login", json={"username": 1, "password": "x"}).status_code == 401

    monkeypatch.setattr(api.db, "get_user", lambda *_: None)
    assert client.post("/api/web/login", json={"username": "student", "password": "x"}).status_code == 401

    monkeypatch.setattr(api.db, "get_user", lambda *_: (1, "student", settings["INITIAL_PASSWORD_HASH"]))
    assert client.post("/api/web/login", json={"username": "student", "password": "wrong"}).status_code == 401

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "get_user", fail)
    assert client.post("/api/web/login", json={"username": "student", "password": "x"}).status_code == 503
    assert all("password" not in line for line in capsys.readouterr().out.splitlines())


def test_login_session_and_logout(monkeypatch, settings, capsys):
    request_ids = []

    def lookup(_url, username, request_id):
        assert username == "student"
        request_ids.append(request_id)
        return (1, username, settings["INITIAL_PASSWORD_HASH"])

    monkeypatch.setattr(api.db, "get_user", lookup)
    client = api.create_app(settings, initialize=False).test_client()
    response = client.post("/api/web/login", json={"username": "student", "password": "correct-password"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert client.get("/api/web/me").json == {"username": "student"}
    assert client.post("/api/web/logout").status_code == 200
    assert client.get("/api/web/me").status_code == 401
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["request_id"] == request_ids[0]
    assert [event["operation"] for event in events] == ["login", "me", "logout", "me"]
