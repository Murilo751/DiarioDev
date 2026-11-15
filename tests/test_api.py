import datetime
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


VALID = {"title": "Git", "topic": "Worktree", "summary": "Estudo", "study_date": "2026-11-15", "minutes": 30}
ROW = (1, "Git", "Worktree", "Estudo", datetime.date(2026, 11, 15), 30, "active")


def logged_in_client(monkeypatch, settings):
    monkeypatch.setattr(api.db, "get_user", lambda *_: (1, "student", settings["INITIAL_PASSWORD_HASH"]))
    client = api.create_app(settings, initialize=False).test_client()
    client.post("/api/web/login", json={"username": "student", "password": "correct-password"})
    return client


def test_record_routes_require_login(settings):
    client = api.create_app(settings, initialize=False).test_client()
    assert client.post("/api/web/records", json=VALID).status_code == 401
    assert client.put("/api/web/records/1", json=VALID).status_code == 401
    assert client.patch("/api/web/records/1/status", json={"status": "inactive"}).status_code == 401


def test_create_record(monkeypatch, settings, capsys):
    client = logged_in_client(monkeypatch, settings)
    calls = []
    monkeypatch.setattr(api.db, "create_record", lambda url, record, rid: calls.append((record, rid)) or ROW)
    capsys.readouterr()
    response = client.post("/api/web/records", json={**VALID, "title": "  Git  "})
    assert response.status_code == 201
    assert response.json == {"id": 1, "title": "Git", "topic": "Worktree", "summary": "Estudo",
                             "study_date": "2026-11-15", "minutes": 30, "status": "active"}
    assert calls[0][0]["title"] == "Git" and calls[0][0]["study_date"] == datetime.date(2026, 11, 15)
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "create" and event["request_id"] == calls[0][1]


def test_record_validation_errors(monkeypatch, settings):
    client = logged_in_client(monkeypatch, settings)
    response = client.post("/api/web/records", json=["invalid"])
    assert response.status_code == 400
    assert set(response.json["errors"]) == {"title", "topic", "summary", "study_date", "minutes"}
    invalid = {"title": "x" * 121, "topic": 5, "summary": "  ", "study_date": "2026-13-45", "minutes": True}
    errors = client.put("/api/web/records/1", json=invalid).json["errors"]
    assert set(errors) == {"title", "topic", "summary", "study_date", "minutes"}
    assert client.post("/api/web/records", json={**VALID, "minutes": -1}).status_code == 400
    assert client.post("/api/web/records", json={**VALID, "minutes": "30"}).status_code == 400
    assert client.post("/api/web/records", json={**VALID, "study_date": 20261115}).status_code == 400


def test_update_record_found_missing_and_failure(monkeypatch, settings):
    client = logged_in_client(monkeypatch, settings)
    monkeypatch.setattr(api.db, "update_record", lambda url, rid_, record, request_id: ROW)
    response = client.put("/api/web/records/1", json=VALID)
    assert response.status_code == 200 and response.json["id"] == 1

    monkeypatch.setattr(api.db, "update_record", lambda *_: None)
    assert client.put("/api/web/records/99", json=VALID).status_code == 404

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "update_record", fail)
    assert client.put("/api/web/records/1", json=VALID).status_code == 503

    monkeypatch.setattr(api.db, "create_record", fail)
    assert client.post("/api/web/records", json=VALID).status_code == 503


def test_cli_health_token_and_protected_command(monkeypatch, settings, capsys):
    request_ids = []

    def lookup(_url, username, request_id, client):
        assert username == "student" and client == "cli"
        request_ids.append(request_id)
        return (1, username, settings["INITIAL_PASSWORD_HASH"])

    monkeypatch.setattr(api.db, "get_user", lookup)
    client = api.create_app(settings, initialize=False).test_client()
    assert client.get("/api/cli/health").json == {"status": "ok"}
    assert client.get("/api/cli/me").status_code == 401
    assert client.get("/api/cli/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
    response = client.post("/api/cli/token", json={
        "username": "student", "password": "correct-password",
    })
    assert response.status_code == 200
    assert response.json["token_type"] == "Bearer"
    assert response.json["expires_in"] == 3600
    token = response.json["token"]
    assert client.get("/api/cli/me", headers={"Authorization": f"Bearer {token}"}).json == {
        "username": "student",
    }
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["operation"] for event in events] == ["health", "me", "me", "token", "me"]
    assert all(event["client"] == "cli" for event in events)
    assert events[3]["request_id"] == request_ids[0]
    assert token not in str(events)


def test_cli_token_failures(monkeypatch, settings, capsys):
    client = api.create_app(settings, initialize=False).test_client()
    assert client.post("/api/cli/token", json=["invalid"]).status_code == 401
    assert client.post("/api/cli/token", json={"username": 1, "password": "x"}).status_code == 401

    monkeypatch.setattr(api.db, "get_user", lambda *_: None)
    assert client.post("/api/cli/token", json={"username": "student", "password": "x"}).status_code == 401
    monkeypatch.setattr(api.db, "get_user", lambda *_: (1, "student", settings["INITIAL_PASSWORD_HASH"]))
    assert client.post("/api/cli/token", json={"username": "student", "password": "wrong"}).status_code == 401

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "get_user", fail)
    assert client.post("/api/cli/token", json={"username": "student", "password": "x"}).status_code == 503
    assert "password" not in capsys.readouterr().out


def test_change_status(monkeypatch, settings, capsys):
    client = logged_in_client(monkeypatch, settings)
    calls = []
    inactive = ROW[:6] + ("inactive",)
    monkeypatch.setattr(api.db, "update_status", lambda url, rid_, status, request_id: calls.append((rid_, status, request_id)) or inactive)
    capsys.readouterr()
    response = client.patch("/api/web/records/1/status", json={"status": "inactive"})
    assert response.status_code == 200 and response.json["status"] == "inactive"
    event = json.loads(capsys.readouterr().out)
    assert calls[0][:2] == (1, "inactive") and event["operation"] == "status"
    assert event["request_id"] == calls[0][2]


def test_change_status_errors(monkeypatch, settings):
    client = logged_in_client(monkeypatch, settings)
    for body in ({"status": "paused"}, {}, ["inactive"]):
        response = client.patch("/api/web/records/1/status", json=body)
        assert response.status_code == 400 and "status" in response.json["errors"]
    monkeypatch.setattr(api.db, "update_status", lambda *_: None)
    assert client.patch("/api/web/records/99/status", json={"status": "active"}).status_code == 404

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "update_status", fail)
    assert client.patch("/api/web/records/1/status", json={"status": "active"}).status_code == 503
