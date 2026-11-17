"""Interactive menu -> real HTTP API -> PostgreSQL -> Web, with isolated data."""

import csv
import io
import json
import os
from threading import Thread
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

import api
import cli


@pytest.fixture
def menu_backend():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration checks")
    schema = "menu_test_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    server = thread = None
    try:
        app = api.create_app({
            "TESTING": True, "SECRET_KEY": "menu-test-only-secret",
            "DATABASE_URL": make_conninfo(database_url, options=f"-c search_path={schema}"),
            "INITIAL_USERNAME": "menu-test",
            "INITIAL_PASSWORD_HASH": generate_password_hash("menu-test-only-password"),
        })
        web = app.test_client()
        assert web.post("/api/web/login", json={
            "username": "menu-test", "password": "menu-test-only-password",
        }).status_code == 200
        server = make_server("127.0.0.1", 0, app)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{server.server_port}", web
    finally:
        if server:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_menu_crud_filters_export_and_dashboard_match_web(menu_backend, monkeypatch, capsys, tmp_path):
    base_url, web = menu_backend
    for number in range(7):
        assert web.post("/api/web/records", json={
            "title": f"Estudo Git {number}", "topic": "Git", "summary": "Preparação da paginação",
            "study_date": "2026-11-16", "minutes": number,
        }).status_code == 201
    assert web.post("/api/web/records", json={
        "title": "Outro assunto", "topic": "Docker", "summary": "Fora dos filtros",
        "study_date": "2026-10-01", "minutes": 10,
    }).status_code == 201
    output_path = tmp_path / "menu.csv"

    def all_records():
        return web.get("/api/web/records/search?sort=title&direction=asc&page=1").json

    def answers():
        yield "menu-test"
        yield "1"
        yield 'Acentuação, "Git"'
        yield "Git"
        yield "Estudo criado pelo menu"
        yield "2026-11-16"
        yield "30"
        original = all_records()["items"][0]
        assert original["title"] == 'Acentuação, "Git"' and original["minutes"] == 30
        original_id = str(original["id"])
        yield "2"
        yield original_id
        yield "1"
        yield ""
        yield ""
        yield ""
        yield ""
        yield "45"
        assert all_records()["items"][0] == {**original, "minutes": 45}
        yield "2"
        yield original_id
        yield "2"
        updated = all_records()["items"][0]
        assert updated["status"] == "inactive" and updated["minutes"] == 45
        yield "2"
        yield original_id
        yield "3"
        copies = [item for item in all_records()["items"] if item["title"] == original["title"]]
        assert len(copies) == 2
        copied = next(item for item in copies if item["id"] != original["id"])
        assert {**copied, "id": original["id"]} == updated
        yield "2"
        yield str(copied["id"])
        yield "4"
        yield "n"
        assert all_records()["total"] == 10
        yield "2"
        yield str(copied["id"])
        yield "4"
        yield "s"
        assert all_records()["total"] == 9 and all_records()["items"][0] == updated
        yield "3"
        yield "1"
        yield "menu-test"
        yield "Git"
        yield "2026-11-01"
        yield "2026-11-30"
        yield "4"
        yield "2"
        yield "1"
        yield "8"
        yield "5"
        yield str(output_path)
        rows = list(csv.DictReader(io.StringIO(output_path.read_bytes().decode("utf-8-sig"))))
        assert len(rows) == 8
        assert rows[0]["title"] == original["title"] and rows[0]["minutes"] == "45"
        expected_ids = []
        query = "author=menu-test&category=Git&date_from=2026-11-01&date_to=2026-11-30&sort=title&direction=asc"
        for page in (1, 2):
            result = web.get(f"/api/web/records/search?{query}&page={page}").json
            expected_ids.extend(str(item["id"]) for item in result["items"])
        assert [item["id"] for item in rows] == expected_ids
        yield "6"
        yield ""
        code, credentials = cli.call_api(base_url, "/api/cli/token", "POST", {
            "username": "menu-test", "password": "menu-test-only-password",
        })
        assert code == 200
        status, cli_dashboard = cli.call_api(base_url, "/api/cli/dashboard", token=credentials["token"])
        assert status == 200 and cli_dashboard == web.get("/api/web/dashboard").json
        yield "3"
        yield "2"
        yield "9"
        yield ":voltar"

    steps = answers()
    monkeypatch.setattr("builtins.input", lambda prompt: next(steps))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "menu-test-only-password")
    monkeypatch.delenv("DIARIODEV_TOKEN", raising=False)
    assert cli.main(["--api-url", base_url, "menu"]) == 0
    with pytest.raises(StopIteration):
        next(steps)
    output = capsys.readouterr().out
    assert "Estudo atualizado" in output and "Estudo excluído" in output
    assert "Página 2 de 2" in output and "DIARIODEV / DASHBOARD" in output
    assert "menu-test-only-password" not in output
    events = [json.loads(line) for line in output.splitlines() if line.startswith('{"timestamp"')]
    layers = {}
    operations = set()
    for event in events:
        if event["client"] == "cli" and event["status"] == "success":
            layers.setdefault(event["request_id"], set()).add(event["layer"])
            operations.add(event["operation"])
    assert any(value == {"api", "db"} for value in layers.values())
    assert {"create", "update", "duplicate", "delete", "search", "export", "dashboard"} <= operations
