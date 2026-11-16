"""CLI -> HTTP API -> PostgreSQL -> Web checks in an isolated temporary schema."""

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
def duplicate_app():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration checks")
    schema = "duplicate_test_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield api.create_app({
            "TESTING": True, "SECRET_KEY": "duplicate-test-only",
            "DATABASE_URL": make_conninfo(database_url, options=f"-c search_path={schema}"),
            "INITIAL_USERNAME": "duplicate-test",
            "INITIAL_PASSWORD_HASH": generate_password_hash("test-only-password"),
        })
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("status", ["active", "inactive"])
def test_cli_duplicate_visible_on_web_and_original_unchanged(duplicate_app, capsys, status):
    app = duplicate_app
    web = app.test_client()
    assert web.post("/api/web/login", json={
        "username": "duplicate-test", "password": "test-only-password",
    }).status_code == 200
    # Use another author for the original to check both authors independently.
    with web.session_transaction() as session:
        session["username"] = "original-author"
    original = web.post("/api/web/records", json={
        "title": "Revisão Git", "topic": "Worktree", "summary": "Cópia\ncom acentos",
        "study_date": "2026-11-16", "minutes": 0,
    }).json
    original_id = original["id"]
    assert web.patch(f"/api/web/records/{original_id}/status",
                     json={"status": status}).status_code == 200
    with psycopg.connect(app.config["DATABASE_URL"]) as connection:
        before = connection.execute("SELECT * FROM records WHERE id = %s",
                                    (original_id,)).fetchone()

    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        code, credentials = cli.call_api(base_url, "/api/cli/token", "POST", {
            "username": "duplicate-test", "password": "test-only-password",
        })
        assert code == 200
        arguments = ["--api-url", base_url, "--token", credentials["token"],
                     "duplicate", str(original_id)]
        assert cli.main(arguments) == 0
        assert cli.main(arguments) == 0
        assert cli.main([*arguments[:-1], "999999"]) == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    response = web.get("/api/web/records")
    assert response.status_code == 200 and response.json["total"] == 3
    items = response.json["items"]
    assert len({item["id"] for item in items}) == 3
    original["status"] = status
    assert next(item for item in items if item["id"] == original_id) == original
    for copy in items:
        assert {**copy, "id": original_id} == original
    output = capsys.readouterr()
    for copy in items:
        if copy["id"] != original_id:
            assert f"Novo registro: #{copy['id']}." in output.out
    assert "HTTP 404: Record not found" in output.err
    with psycopg.connect(app.config["DATABASE_URL"]) as connection:
        assert connection.execute("SELECT * FROM records WHERE id = %s",
                                  (original_id,)).fetchone() == before
        authors = connection.execute("SELECT id, author FROM records ORDER BY id").fetchall()
        assert authors == [(original_id, "original-author"),
                           (items[1]["id"], "duplicate-test"),
                           (items[0]["id"], "duplicate-test")]
