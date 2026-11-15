import datetime
import csv
import io
import json
from unittest.mock import MagicMock

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
    assert client.get("/api/web/records").status_code == 401
    assert client.delete("/api/web/records/1").status_code == 401
    assert client.get("/api/web/records/search").status_code == 401
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
    assert calls[0][0]["author"] == "student"
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


def test_list_records_pagination_sort_and_errors(monkeypatch, settings, capsys):
    client = logged_in_client(monkeypatch, settings)
    calls = []
    monkeypatch.setattr(api.db, "list_records", lambda *args: calls.append(args) or ([ROW], 11))
    capsys.readouterr()
    response = client.get("/api/web/records?page=2&sort=title&direction=asc")
    assert response.status_code == 200
    assert response.json == {"items": [api.serialize_record(ROW)], "page": 2,
                             "page_size": 5, "total": 11, "total_pages": 3}
    assert calls[0][1:4] == (2, "title", "asc")
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "list" and event["request_id"] == calls[0][4]

    assert client.get("/api/web/records?page=0").status_code == 400
    assert client.get("/api/web/records?page=nope").status_code == 400
    assert client.get("/api/web/records?sort=not-a-column").status_code == 400
    assert client.get("/api/web/records?direction=sideways").status_code == 400

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "list_records", fail)
    assert client.get("/api/web/records").status_code == 503


def test_delete_record_success_missing_and_failure(monkeypatch, settings, capsys):
    client = logged_in_client(monkeypatch, settings)
    calls = []
    monkeypatch.setattr(api.db, "delete_record", lambda *args: calls.append(args) or True)
    capsys.readouterr()
    assert client.delete("/api/web/records/7").status_code == 204
    assert calls[0][1] == 7
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "delete" and event["request_id"] == calls[0][2]

    monkeypatch.setattr(api.db, "delete_record", lambda *_: False)
    assert client.delete("/api/web/records/8").status_code == 404

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "delete_record", fail)
    assert client.delete("/api/web/records/7").status_code == 503


def test_search_route_combines_filters_and_handles_invalid_inputs(monkeypatch, settings, capsys):
    client = logged_in_client(monkeypatch, settings)
    calls = []
    monkeypatch.setattr(api.db, "search_records", lambda *args: calls.append(args) or ([ROW], 6))
    capsys.readouterr()
    response = client.get("/api/web/records/search?author=student&category=Work&date_from=2026-11-01&date_to=2026-11-30&page=2&sort=title&direction=asc")
    assert response.status_code == 200
    assert response.json["total_pages"] == 2 and response.json["items"][0]["id"] == 1
    assert calls[0][1]["author"] == "student" and calls[0][1]["category"] == "Work"
    assert calls[0][1]["date_from"] == datetime.date(2026, 11, 1)
    assert calls[0][1]["date_to"] == datetime.date(2026, 11, 30)
    assert calls[0][2:5] == (2, "title", "asc")
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "search" and event["request_id"] == calls[0][5]

    assert client.get("/api/web/records/search").status_code == 200
    assert calls[1][1]["date_from"] is None and calls[1][1]["date_to"] is None
    for query in ("page=nope", "page=0", "sort=bad", "direction=bad",
                  "date_from=bad", "date_to=bad", "date_from=2026-11-30&date_to=2026-11-01"):
        assert client.get("/api/web/records/search?" + query).status_code == 400

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "search_records", fail)
    assert client.get("/api/web/records/search").status_code == 503


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


def cli_record_client(monkeypatch, settings):
    monkeypatch.setattr(api.db, "get_user", lambda *_: (1, "student", settings["INITIAL_PASSWORD_HASH"]))
    client = api.create_app(settings, initialize=False).test_client()
    token = client.post("/api/cli/token", json={
        "username": "student", "password": "correct-password",
    }).json["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_cli_record_routes_require_valid_token(settings):
    client = api.create_app(settings, initialize=False).test_client()
    for path, method in (("/api/cli/records", client.post),
                         ("/api/cli/records/1", client.put)):
        assert method(path, json=VALID).status_code == 401
        assert method(path, json=VALID, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_cli_create_and_edit_share_web_validation_and_persist(monkeypatch, settings, capsys):
    client, headers = cli_record_client(monkeypatch, settings)
    calls = []

    def create(url, record, request_id):
        calls.append(("create", record, request_id))
        return ROW

    def update(url, record_id, record, request_id):
        calls.append(("update", record_id, record, request_id))
        return (record_id, record["title"], record["topic"], record["summary"],
                record["study_date"], record["minutes"], "active")

    monkeypatch.setattr(api.db, "create_record_cli", create)
    monkeypatch.setattr(api.db, "update_record_cli", update)
    capsys.readouterr()
    created = client.post("/api/cli/records", json={**VALID, "title": "  Git  "}, headers=headers)
    assert created.status_code == 201 and created.json["id"] == 1
    assert calls[0][1]["title"] == "Git"
    assert calls[0][1]["author"] == "student"
    edited = client.put("/api/cli/records/1", json={**VALID, "topic": "API"}, headers=headers)
    assert edited.status_code == 200 and edited.json["topic"] == "API"
    assert calls[1][1] == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["operation"] for event in events] == ["create", "update"]
    assert all(event["client"] == "cli" and event["status"] == "success" for event in events)
    assert events[0]["request_id"] == calls[0][2]
    assert events[1]["request_id"] == calls[1][3]


def test_cli_record_validation_missing_and_database_failures(monkeypatch, settings):
    client, headers = cli_record_client(monkeypatch, settings)
    invalid = {**VALID, "title": " ", "study_date": "tomorrow", "minutes": 1441}
    create_error = client.post("/api/cli/records", json=invalid, headers=headers)
    edit_error = client.put("/api/cli/records/1", json=invalid, headers=headers)
    assert create_error.status_code == edit_error.status_code == 400
    assert create_error.json["errors"] == edit_error.json["errors"]
    assert set(create_error.json["errors"]) == {"title", "study_date", "minutes"}

    monkeypatch.setattr(api.db, "update_record_cli", lambda *_: None)
    assert client.put("/api/cli/records/999", json=VALID, headers=headers).status_code == 404

    def fail(*_):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(api.db, "update_record_cli", fail)
    monkeypatch.setattr(api.db, "create_record_cli", fail)
    assert client.put("/api/cli/records/1", json=VALID, headers=headers).status_code == 503
    assert client.post("/api/cli/records", json=VALID, headers=headers).status_code == 503


def test_cli_list_and_delete_require_valid_token(settings):
    client = api.create_app(settings, initialize=False).test_client()
    assert client.get("/api/cli/records").status_code == 401
    assert client.delete("/api/cli/records/1").status_code == 401
    bad = {"Authorization": "Bearer invalid"}
    assert client.get("/api/cli/records", headers=bad).status_code == 401
    assert client.delete("/api/cli/records/1", headers=bad).status_code == 401


def test_cli_list_records_pagination_sort_and_errors(monkeypatch, settings, capsys):
    client, headers = cli_record_client(monkeypatch, settings)
    calls = []
    monkeypatch.setattr(api.db, "list_records_cli", lambda *args: calls.append(args) or ([ROW], 11))
    capsys.readouterr()
    response = client.get("/api/cli/records?page=2&page_size=4&sort=title&direction=asc", headers=headers)
    assert response.status_code == 200
    assert response.json == {"items": [api.serialize_record(ROW)], "page": 2,
                             "page_size": 4, "total": 11, "total_pages": 3}
    assert calls[0][1:5] == (2, 4, "title", "asc")
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["operation"] == "list"
    assert event["request_id"] == calls[0][5]

    assert client.get("/api/cli/records", headers=headers).json["page_size"] == 5
    for query in ("page=0", "page=nope", "page_size=0", "page_size=51", "page_size=x",
                  "sort=not-a-column", "direction=sideways"):
        assert client.get("/api/cli/records?" + query, headers=headers).status_code == 400

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "list_records_cli", fail)
    assert client.get("/api/cli/records", headers=headers).status_code == 503


def test_cli_delete_record_success_missing_and_failure(monkeypatch, settings, capsys):
    client, headers = cli_record_client(monkeypatch, settings)
    calls = []
    monkeypatch.setattr(api.db, "delete_record_cli", lambda *args: calls.append(args) or True)
    capsys.readouterr()
    response = client.delete("/api/cli/records/7", headers=headers)
    assert response.status_code == 200 and response.json == {"id": 7, "deleted": True}
    assert calls[0][1] == 7
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["operation"] == "delete"
    assert event["request_id"] == calls[0][2]

    monkeypatch.setattr(api.db, "delete_record_cli", lambda *_: False)
    assert client.delete("/api/cli/records/8", headers=headers).status_code == 404

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "delete_record_cli", fail)
    assert client.delete("/api/cli/records/7", headers=headers).status_code == 503


def test_cli_status_requires_valid_token(settings):
    client = api.create_app(settings, initialize=False).test_client()
    body = {"status": "inactive"}
    assert client.patch("/api/cli/records/1/status", json=body).status_code == 401
    bad = {"Authorization": "Bearer invalid"}
    assert client.patch("/api/cli/records/1/status", json=body, headers=bad).status_code == 401


def test_cli_change_status_success_and_validation(monkeypatch, settings, capsys):
    client, headers = cli_record_client(monkeypatch, settings)
    calls = []
    inactive = ROW[:6] + ("inactive",)
    monkeypatch.setattr(api.db, "update_status_cli", lambda *args: calls.append(args) or inactive)
    capsys.readouterr()
    response = client.patch("/api/cli/records/1/status", json={"status": "inactive"}, headers=headers)
    assert response.status_code == 200 and response.json["status"] == "inactive"
    assert calls[0][1:3] == (1, "inactive")
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["operation"] == "status"
    assert event["request_id"] == calls[0][3]
    for body in ({"status": "paused"}, {}, ["inactive"]):
        response = client.patch("/api/cli/records/1/status", json=body, headers=headers)
        assert response.status_code == 400 and "status" in response.json["errors"]


def test_cli_change_status_missing_and_database_failure(monkeypatch, settings):
    client, headers = cli_record_client(monkeypatch, settings)
    monkeypatch.setattr(api.db, "update_status_cli", lambda *_: None)
    assert client.patch("/api/cli/records/99/status", json={"status": "active"},
                        headers=headers).status_code == 404

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "update_status_cli", fail)
    assert client.patch("/api/cli/records/1/status", json={"status": "active"},
                        headers=headers).status_code == 503


def csv_rows(response):
    return list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig"), newline="")))


def test_export_requires_session(settings, monkeypatch):
    query = MagicMock()
    monkeypatch.setattr(api.db, "export_records", query)
    client = api.create_app(settings, initialize=False).test_client()
    assert client.get("/api/web/records/export").status_code == 401
    client.set_cookie("session", "invalid")
    assert client.get("/api/web/records/export").status_code == 401
    query.assert_not_called()


def test_export_all_rows_ignores_pagination_and_correlates_logs(monkeypatch, settings, capsys):
    client = logged_in_client(monkeypatch, settings)
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(number, *ROW[1:]) for number in range(1, 13)]
    monkeypatch.setattr(api.db.psycopg, "connect", MagicMock(return_value=connection))
    capsys.readouterr()
    response = client.get("/api/web/records/export?page=2&page_size=5&limit=5&offset=5")
    assert response.status_code == 200
    assert response.content_type == "text/csv; charset=utf-8"
    assert response.headers["Content-Disposition"] == 'attachment; filename="registros.csv"'
    assert response.headers["Cache-Control"] == "no-store"
    assert response.data.startswith(b"\xef\xbb\xbf")
    assert len(csv_rows(response)) == 12
    assert [row["id"] for row in csv_rows(response)] == [str(n) for n in range(1, 13)]
    sql, parameters = cursor.execute.call_args.args
    assert "LIMIT" not in sql and "OFFSET" not in sql and "WHERE" not in sql
    assert parameters == ()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["layer"] for event in events] == ["db", "api"]
    assert all(event["operation"] == "export" and event["status"] == "success"
               and event["client"] == "web" for event in events)
    assert events[0]["request_id"] == events[1]["request_id"]


def test_export_combines_filters_and_preserves_csv_fields(monkeypatch, settings):
    client = logged_in_client(monkeypatch, settings)
    row = (8, 'Revisão, "Git"', "Ação", "Linha 1\nLinha 2", ROW[4], 0, "inactive")
    query = MagicMock(return_value=[row] * 8)
    monkeypatch.setattr(api.db, "export_records", query)
    response = client.get("/api/web/records/export", query_string={
        "author": "  student ", "category": " Ação ", "date_from": "2026-11-01",
        "date_to": "2026-11-30", "sort": "title", "direction": "asc", "page": 999,
    })
    assert response.status_code == 200 and len(csv_rows(response)) == 8
    assert query.call_args.args[1:4] == (
        {"author": "student", "category": "Ação", "date_from": datetime.date(2026, 11, 1),
         "date_to": datetime.date(2026, 11, 30)}, "title", "asc",
    )
    assert csv_rows(response)[0] == {
        "id": "8", "title": row[1], "topic": row[2], "summary": row[3],
        "study_date": "2026-11-15", "minutes": "0", "status": "inactive",
    }


def test_export_empty_result_has_header(monkeypatch, settings):
    client = logged_in_client(monkeypatch, settings)
    query = MagicMock(return_value=[])
    monkeypatch.setattr(api.db, "export_records", query)
    response = client.get("/api/web/records/export?author=%20%20&category=")
    assert response.status_code == 200 and csv_rows(response) == []
    assert response.data.decode("utf-8-sig") == "id,title,topic,summary,study_date,minutes,status\r\n"
    assert query.call_args.args[1] == {}


@pytest.mark.parametrize("query", [
    {"date_from": "bad"},
    {"date_to": "2026-02-30"}, {"date_from": "2026-11-15", "date_to": "2026-11-14"},
    {"sort": "title; DROP TABLE records"}, {"direction": "sideways"}, {"unknown": "Git"},
])
def test_export_rejects_invalid_filters_before_database(monkeypatch, settings, query, capsys):
    client = logged_in_client(monkeypatch, settings)
    export = MagicMock()
    monkeypatch.setattr(api.db, "export_records", export)
    capsys.readouterr()
    response = client.get("/api/web/records/export", query_string=query)
    assert response.status_code == 400 and response.json["errors"]
    export.assert_not_called()
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "export" and event["status"] == "error"


def test_export_database_failure_logs_both_layers(monkeypatch, settings, capsys):
    client = logged_in_client(monkeypatch, settings)
    monkeypatch.setattr(api.db.psycopg, "connect", MagicMock(side_effect=RuntimeError("db failed")))
    capsys.readouterr()
    response = client.get("/api/web/records/export")
    assert response.status_code == 503 and response.json == {"error": "Export unavailable"}
    assert "Content-Disposition" not in response.headers
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["layer"] for event in events] == ["db", "api"]
    assert all(event["operation"] == "export" and event["status"] == "error" for event in events)
    assert events[0]["request_id"] == events[1]["request_id"]


def test_cli_search_requires_valid_token(settings):
    client = api.create_app(settings, initialize=False).test_client()
    assert client.get("/api/cli/records/search").status_code == 401
    assert client.get("/api/cli/records/search", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_cli_search_combines_filters_like_the_web(monkeypatch, settings, capsys):
    client, headers = cli_record_client(monkeypatch, settings)
    web_calls, cli_calls = [], []
    monkeypatch.setattr(api.db, "search_records_cli", lambda *args: cli_calls.append(args) or ([ROW], 6))
    capsys.readouterr()
    query = "author=student&category=Work&date_from=2026-11-01&date_to=2026-11-30&sort=title&direction=asc"
    response = client.get(f"/api/cli/records/search?{query}&page=2&page_size=4", headers=headers)
    assert response.status_code == 200
    assert response.json == {"items": [api.serialize_record(ROW)], "page": 2,
                             "page_size": 4, "total": 6, "total_pages": 2}
    filters = cli_calls[0][1]
    assert filters == {"author": "student", "category": "Work",
                       "date_from": datetime.date(2026, 11, 1), "date_to": datetime.date(2026, 11, 30)}
    assert cli_calls[0][2:6] == (2, 4, "title", "asc")
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["operation"] == "search"
    assert event["request_id"] == cli_calls[0][6]

    # The same parameters reach the Web search with the same filters.
    monkeypatch.setattr(api.db, "search_records", lambda *args: web_calls.append(args) or ([ROW], 6))
    web = logged_in_client(monkeypatch, settings)
    assert web.get(f"/api/web/records/search?{query}").status_code == 200
    assert web_calls[0][1] == filters

    assert client.get("/api/cli/records/search", headers=headers).json["page_size"] == 5
    assert cli_calls[1][1]["date_from"] is None and cli_calls[1][1]["date_to"] is None


def test_cli_search_invalid_parameters_and_database_failure(monkeypatch, settings):
    client, headers = cli_record_client(monkeypatch, settings)
    for query in ("page=0", "page=nope", "page_size=0", "page_size=51", "sort=bad", "direction=bad",
                  "date_from=bad", "date_to=bad", "date_from=2026-11-30&date_to=2026-11-01"):
        assert client.get("/api/cli/records/search?" + query, headers=headers).status_code == 400

    def fail(*_):
        raise RuntimeError("db failed")

    monkeypatch.setattr(api.db, "search_records_cli", fail)
    assert client.get("/api/cli/records/search", headers=headers).status_code == 503
