import json
from unittest.mock import MagicMock

import pytest

import db


def connection_mock(monkeypatch):
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(db.psycopg, "connect", connect)
    return connect, cursor


def test_initialize_creates_schema_and_updates_initial_user(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    db.initialize("database-url", "student", "scrypt:hash", "req-1")
    connect.assert_called_once_with("database-url")
    assert cursor.execute.call_count == 3
    assert cursor.execute.call_args.args[1] == ("student", "scrypt:hash")
    event = json.loads(capsys.readouterr().out)
    assert event["layer"] == "db" and event["request_id"] == "req-1"
    assert event["operation"] == "initialize" and event["status"] == "success"


def test_initialize_failure_is_logged(monkeypatch, capsys):
    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.initialize("database-url", "student", "hash", "req-2")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_user_lookup_and_failure(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (1, "student", "hash")
    assert db.get_user("database-url", "student", "req-3") == (1, "student", "hash")
    connect.assert_called_once_with("database-url")
    assert cursor.execute.call_args.args[1] == ("student",)
    success = json.loads(capsys.readouterr().out)
    assert success["operation"] == "get_user" and success["status"] == "success"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.get_user("database-url", "student", "req-4")
    failure = json.loads(capsys.readouterr().out)
    assert failure["request_id"] == "req-4" and failure["status"] == "error"
