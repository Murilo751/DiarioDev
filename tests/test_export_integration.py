"""Optional end-to-end export checks against PostgreSQL in a temporary schema."""

import csv
import io
import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from werkzeug.security import generate_password_hash

import api


@pytest.fixture
def export_client():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration checks")
    schema = "export_test_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        app = api.create_app({
            "TESTING": True, "SECRET_KEY": "integration-test-only",
            "DATABASE_URL": make_conninfo(database_url, options=f"-c search_path={schema}"),
            "INITIAL_USERNAME": "export-test",
            "INITIAL_PASSWORD_HASH": generate_password_hash("test-only-password"),
        })
        client = app.test_client()
        assert client.post("/api/web/login", json={
            "username": "export-test", "password": "test-only-password",
        }).status_code == 200
        yield client
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_export_filters_all_pages_with_real_postgresql(export_client):
    client = export_client
    expected = []
    for number in range(12):
        record = {"title": f'Revisão Git, "{number}"', "topic": "Worktree",
                  "summary": "Ação\nSegunda linha", "study_date": "2026-11-15", "minutes": number}
        response = client.post("/api/web/records", json=record)
        assert response.status_code == 201
        expected.append(str(response.json["id"]))
    for changes in ({"topic": "Flask"},
                    {"study_date": "2026-11-14"}, {"study_date": "2026-11-16"},
                    {"topic": "100%_literal"}):
        assert client.post("/api/web/records", json={**record, **changes}).status_code == 201
    with client.session_transaction() as session:
        session["username"] = "another-author"
    assert client.post("/api/web/records", json=record).status_code == 201

    def download(query):
        response = client.get("/api/web/records/export", query_string=query)
        assert response.status_code == 200
        return list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig"), newline="")))

    assert len(client.get("/api/web/records?page=2").json["items"]) == 5
    assert len(download({"page": 2, "limit": 5})) == 17
    filters = {"author": "EXPORT-test", "category": "WORKtree", "date_from": "2026-11-15",
               "date_to": "2026-11-15", "page": 2, "page_size": 5}
    rows = download(filters)
    assert {row["id"] for row in rows} == set(expected)
    assert rows[0]["summary"] == "Ação\nSegunda linha"
    assert rows[0]["title"].startswith('Revisão Git, "')
    search_ids = []
    for page in range(1, 4):
        result = client.get("/api/web/records/search", query_string={**filters, "page": page}).json
        assert result["total"] == 12
        search_ids.extend(str(row["id"]) for row in result["items"])
    assert [row["id"] for row in rows] == search_ids
    assert len(download({"date_from": "2026-11-16"})) == 1
    assert len(download({"date_to": "2026-11-14"})) == 1
    assert len(download({"category": "%_"})) == 1
    assert download({"author": "' OR 1=1 --"}) == []
    assert download({"author": "export"}) == []
    assert download({"category": "inexistente"}) == []


def test_cli_creation_remains_compatible_with_author_migration(export_client):
    client = export_client
    response = client.post("/api/cli/token", json={
        "username": "export-test", "password": "test-only-password",
    })
    headers = {"Authorization": "Bearer " + response.json["token"]}
    created = client.post("/api/cli/records", headers=headers, json={
        "title": "Registro CLI", "topic": "CSV", "summary": "Criado pela CLI",
        "study_date": "2026-11-15", "minutes": 30,
    })
    assert created.status_code == 201
    response = client.get("/api/web/records/export?author=export-test&category=CSV")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig"))))
    assert [row["id"] for row in rows] == [str(created.json["id"])]
