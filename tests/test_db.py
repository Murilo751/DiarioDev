import json
from datetime import date
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
    assert cursor.execute.call_count == 7
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


RECORD = {"title": "Git", "topic": "Worktree", "summary": "Estudo", "study_date": "2026-11-15", "minutes": 30, "author": "student"}


def test_create_record_and_failure(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (1, "Git", "Worktree", "Estudo", "2026-11-15", 30, "active")
    assert db.create_record("database-url", RECORD, "req-5")[0] == 1
    assert cursor.execute.call_args.args[1] == ("Git", "Worktree", "Estudo", "2026-11-15", 30, "student")
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "insert" and event["request_id"] == "req-5"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.create_record("database-url", RECORD, "req-6")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_update_record_found_missing_and_failure(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (7, "Git", "Worktree", "Estudo", "2026-11-15", 30, "active")
    assert db.update_record("database-url", 7, RECORD, "req-7")[0] == 7
    assert cursor.execute.call_args.args[1][-1] == 7
    assert "updated" in json.loads(capsys.readouterr().out)["message"]

    cursor.fetchone.return_value = None
    assert db.update_record("database-url", 8, RECORD, "req-8") is None
    assert "not found" in json.loads(capsys.readouterr().out)["message"]

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.update_record("database-url", 7, RECORD, "req-9")
    assert json.loads(capsys.readouterr().out)["operation"] == "update"

def test_cli_user_lookup_logs_cli_client(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (1, "student", "hash")
    assert db.get_user("database-url", "student", "req-cli", "cli") == (1, "student", "hash")
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["request_id"] == "req-cli"

def test_list_records_uses_stable_page_and_logs(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (11,)
    cursor.fetchall.return_value = [(7, "Git", "Worktree", "Estudo", "2026-11-15", 30)]
    rows, total = db.list_records("database-url", 2, "title", "asc", "req-list")
    assert total == 11 and rows[0][0] == 7
    assert "ORDER BY title ASC, id DESC" in cursor.execute.call_args.args[0]
    assert cursor.execute.call_args.args[1] == (5, 5)
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "web" and event["request_id"] == "req-list"

    db.list_records("database-url", 1, "minutes", "desc", "req-desc")
    assert "ORDER BY minutes DESC, id DESC" in cursor.execute.call_args.args[0]
    capsys.readouterr()

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.list_records("database-url", 1, "title", "asc", "req-error")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_search_combines_filters_and_logs_reads(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [(7, "Git", "Worktree", "Estudo", "2026-11-15", 30, "active")]
    filters = {"author": "student", "category": "Work", "date_from": "2026-11-01", "date_to": "2026-11-30"}
    rows, total = db.search_records("database-url", filters, 2, "title", "asc", "req-search")
    assert total == 1 and rows[0][0] == 7
    assert cursor.execute.call_count == 2
    count_sql, count_args = cursor.execute.call_args_list[0].args
    list_sql, list_args = cursor.execute.call_args_list[1].args
    assert all(fragment in count_sql for fragment in (
        "LOWER(author) = LOWER(%s)", "STRPOS(LOWER(topic), LOWER(%s)) > 0", "study_date >= %s", "study_date <= %s"))
    assert "ORDER BY title ASC, id DESC" in list_sql
    assert count_args == ["student", "Work", "2026-11-01", "2026-11-30"]
    assert list_args == ("student", "Work", "2026-11-01", "2026-11-30", 5, 5)
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "search" and event["request_id"] == "req-search"

    empty = {"author": "", "category": "", "date_from": None, "date_to": None}
    db.search_records("database-url", empty, 1, "minutes", "desc", "req-empty")
    assert "WHERE" not in cursor.execute.call_args.args[0]
    assert "ORDER BY minutes DESC" in cursor.execute.call_args.args[0]
    capsys.readouterr()

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.search_records("database-url", filters, 1, "title", "asc", "req-error")
    assert json.loads(capsys.readouterr().out)["status"] == "error"

def test_delete_record_found_missing_and_failure(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (7,)
    assert db.delete_record("database-url", 7, "req-delete") is True
    assert cursor.execute.call_args.args[1] == (7,)
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "delete" and event["status"] == "success"

    cursor.fetchone.return_value = None
    assert db.delete_record("database-url", 8, "req-missing") is False
    event = json.loads(capsys.readouterr().out)
    assert event["status"] == "error" and event["level"] == "WARN"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.delete_record("database-url", 7, "req-error")
def test_update_status_found_missing_and_failure(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (7, "Git", "Worktree", "Estudo", "2026-11-15", 30, "inactive")
    assert db.update_status("database-url", 7, "inactive", "req-10")[6] == "inactive"
    assert cursor.execute.call_args.args[1] == ("inactive", 7)
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "update_status" and event["request_id"] == "req-10"

    cursor.fetchone.return_value = None
    assert db.update_status("database-url", 8, "active", "req-11") is None
    assert "not found" in json.loads(capsys.readouterr().out)["message"]

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.update_status("database-url", 7, "active", "req-12")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_cli_insert_uses_records_table_and_logs_result(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (17, "Git", "Worktree", "Estudo", "2026-11-15", 30, "active")
    assert db.create_record_cli("database-url", RECORD, "req-cli-create")[0] == 17
    connect.assert_called_once_with("database-url")
    sql, values = cursor.execute.call_args.args
    assert "INSERT INTO records" in sql and "RETURNING" in sql
    assert values == ("Git", "Worktree", "Estudo", "2026-11-15", 30, "student")
    event = json.loads(capsys.readouterr().out)
    assert (event["client"], event["operation"], event["status"], event["request_id"]) == (
        "cli", "insert", "success", "req-cli-create",
    )

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.create_record_cli("database-url", RECORD, "req-cli-create-failed")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_cli_update_found_missing_and_failure(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (17, "Git", "Worktree", "Estudo", "2026-11-15", 30, "active")
    assert db.update_record_cli("database-url", 17, RECORD, "req-cli-edit")[0] == 17
    sql, values = cursor.execute.call_args.args
    assert "UPDATE records SET" in sql and "RETURNING" in sql and values[-1] == 17
    event = json.loads(capsys.readouterr().out)
    assert (event["client"], event["operation"], event["status"], event["request_id"]) == (
        "cli", "update", "success", "req-cli-edit",
    )

    cursor.fetchone.return_value = None
    assert db.update_record_cli("database-url", 999, RECORD, "req-cli-missing") is None
    event = json.loads(capsys.readouterr().out)
    assert event["level"] == "WARN" and event["status"] == "error"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.update_record_cli("database-url", 17, RECORD, "req-cli-edit-failed")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_list_records_cli_uses_requested_page_and_logs_cli(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (11,)
    cursor.fetchall.return_value = [(7, "Git", "Worktree", "Estudo", "2026-11-15", 30, "active")]
    rows, total = db.list_records_cli("database-url", 2, 3, "title", "asc", "req-cli-list")
    assert total == 11 and rows[0][0] == 7
    assert "ORDER BY title ASC, id DESC" in cursor.execute.call_args.args[0]
    assert cursor.execute.call_args.args[1] == (3, 3)
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["operation"] == "list"
    assert event["layer"] == "db" and event["request_id"] == "req-cli-list"

    db.list_records_cli("database-url", 1, 5, "minutes", "desc", "req-cli-desc")
    assert "ORDER BY minutes DESC, id DESC" in cursor.execute.call_args.args[0]
    capsys.readouterr()

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.list_records_cli("database-url", 1, 5, "title", "asc", "req-cli-error")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_delete_record_cli_found_missing_and_failure(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (7,)
    assert db.delete_record_cli("database-url", 7, "req-cli-delete") is True
    assert cursor.execute.call_args.args[1] == (7,)
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["operation"] == "delete" and event["status"] == "success"

    cursor.fetchone.return_value = None
    assert db.delete_record_cli("database-url", 8, "req-cli-missing") is False
    assert json.loads(capsys.readouterr().out)["status"] == "error"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.delete_record_cli("database-url", 7, "req-cli-error")
    assert json.loads(capsys.readouterr().out)["level"] == "ERROR"


def test_update_status_cli_found_missing_and_failure(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (7, "Git", "Worktree", "Estudo", "2026-11-15", 30, "inactive")
    assert db.update_status_cli("database-url", 7, "inactive", "req-cli-status")[6] == "inactive"
    assert cursor.execute.call_args.args[1] == ("inactive", 7)
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["operation"] == "update_status"
    assert event["layer"] == "db" and event["request_id"] == "req-cli-status"

    cursor.fetchone.return_value = None
    assert db.update_status_cli("database-url", 8, "active", "req-cli-missing") is None
    assert json.loads(capsys.readouterr().out)["status"] == "error"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.update_status_cli("database-url", 7, "active", "req-cli-error")
    assert json.loads(capsys.readouterr().out)["level"] == "ERROR"


def test_export_records_combines_parameterized_filters_without_pagination(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    cursor.fetchall.return_value = [tuple(range(7))] * 12
    filters = {"author": "student' OR 1=1 --", "category": "Worktree",
               "date_from": date(2026, 11, 1), "date_to": date(2026, 11, 15)}
    rows = db.export_records("database-url", filters, "title", "asc", "req-export")
    connect.assert_called_once_with("database-url")
    assert len(rows) == 12
    sql, parameters = cursor.execute.call_args.args
    assert "LOWER(author) = LOWER(%s) AND STRPOS(LOWER(topic), LOWER(%s)) > 0" in sql
    assert "study_date >= %s AND study_date <= %s" in sql
    assert "ORDER BY title ASC, id DESC" in sql
    assert "LIMIT" not in sql and "OFFSET" not in sql and filters["author"] not in sql
    assert parameters == tuple(filters.values())
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "export" and event["request_id"] == "req-export"


def test_export_records_without_filters_and_single_date_boundary(monkeypatch):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchall.return_value = []
    assert db.export_records("database-url", {}, "study_date", "desc", "req-empty") == []
    sql, parameters = cursor.execute.call_args.args
    assert "WHERE" not in sql and "ORDER BY study_date DESC, id DESC" in sql
    assert parameters == ()
    db.export_records("database-url", {"date_to": date(2026, 11, 15)}, "minutes", "asc", "req-date")
    assert "WHERE study_date <= %s" in cursor.execute.call_args.args[0]
    assert cursor.execute.call_args.args[1] == (date(2026, 11, 15),)


def test_export_records_failure_is_logged(monkeypatch, capsys):
    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.export_records("database-url", {}, "title", "asc", "req-export-error")
    event = json.loads(capsys.readouterr().out)
    assert event["operation"] == "export" and event["status"] == "error"
    assert event["request_id"] == "req-export-error"


def test_search_records_cli_combines_filters_and_logs_cli_reads(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [(7, "Git", "Worktree", "Estudo", "2026-11-15", 30, "active")]
    filters = {"author": "student", "category": "Work", "date_from": "2026-11-01", "date_to": "2026-11-30"}
    rows, total = db.search_records_cli("database-url", filters, 2, 3, "title", "asc", "req-cli-search")
    assert total == 1 and rows[0][0] == 7
    count_sql, count_args = cursor.execute.call_args_list[0].args
    list_sql, list_args = cursor.execute.call_args_list[1].args
    assert all(fragment in count_sql for fragment in (
        "LOWER(author) = LOWER(%s)", "STRPOS(LOWER(topic), LOWER(%s)) > 0", "study_date >= %s", "study_date <= %s"))
    assert "ORDER BY title ASC, id DESC" in list_sql
    assert count_args == ["student", "Work", "2026-11-01", "2026-11-30"]
    assert list_args == ("student", "Work", "2026-11-01", "2026-11-30", 3, 3)
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["layer"] == "db"
    assert event["operation"] == "search" and event["request_id"] == "req-cli-search"

    empty = {"author": "", "category": "", "date_from": None, "date_to": None}
    db.search_records_cli("database-url", empty, 1, 5, "minutes", "desc", "req-cli-empty")
    assert "WHERE" not in cursor.execute.call_args.args[0]
    assert "ORDER BY minutes DESC" in cursor.execute.call_args.args[0]
    capsys.readouterr()

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.search_records_cli("database-url", filters, 1, 5, "title", "asc", "req-cli-error")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_duplicate_record_found_missing_and_failure(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchone.return_value = (9, "Git", "Worktree", "Estudo", "2026-11-15", 30, "inactive")
    assert db.duplicate_record("database-url", 7, "student", "req-dup")[0] == 9
    sql, params = cursor.execute.call_args.args
    assert sql.startswith("INSERT INTO records") and "FROM records WHERE id = %s" in sql
    assert params == ("student", 7)
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "web" and event["operation"] == "duplicate"
    assert event["layer"] == "db" and event["request_id"] == "req-dup"

    cursor.fetchone.return_value = None
    assert db.duplicate_record("database-url", 8, "student", "req-dup-missing") is None
    assert json.loads(capsys.readouterr().out)["status"] == "error"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.duplicate_record("database-url", 7, "student", "req-dup-error")
    assert json.loads(capsys.readouterr().out)["level"] == "ERROR"


def test_dashboard_web_reads_three_groupings_and_logs(monkeypatch, capsys):
    _, cursor = connection_mock(monkeypatch)
    cursor.fetchall.side_effect = [[("Git", 3), ("Docker", 1)], [("admin", 4)], [("2026-10", 1), ("2026-11", 3)]]
    by_category, by_author, by_month = db.dashboard_web("database-url", "req-dash")
    assert by_category == [("Git", 3), ("Docker", 1)]
    assert by_author == [("admin", 4)]
    assert by_month == [("2026-10", 1), ("2026-11", 3)]
    queries = [call.args[0] for call in cursor.execute.call_args_list]
    assert "GROUP BY topic" in queries[0] and "GROUP BY author" in queries[1]
    assert "TO_CHAR(study_date, 'YYYY-MM')" in queries[2]
    assert cursor.execute.call_args_list[0].args[1] == (10,)
    assert cursor.execute.call_args_list[2].args[1] == (12,)
    event = json.loads(capsys.readouterr().out)
    assert event["layer"] == "db" and event["client"] == "web"
    assert event["operation"] == "dashboard" and event["request_id"] == "req-dash"

    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.dashboard_web("database-url", "req-dash-error")
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "error" and failure["request_id"] == "req-dash-error"


def test_export_records_cli_combines_filters_without_pagination(monkeypatch, capsys):
    connect, cursor = connection_mock(monkeypatch)
    cursor.fetchall.return_value = [tuple(range(7))] * 12
    filters = {"author": "student' OR 1=1 --", "category": "Worktree",
               "date_from": date(2026, 11, 1), "date_to": date(2026, 11, 15)}
    assert len(db.export_records_cli("database-url", filters, "title", "asc", "req-cli-export")) == 12
    connect.assert_called_once_with("database-url")
    sql, parameters = cursor.execute.call_args.args
    assert "LOWER(author) = LOWER(%s) AND STRPOS(LOWER(topic), LOWER(%s)) > 0" in sql
    assert "study_date >= %s AND study_date <= %s" in sql and "ORDER BY title ASC, id DESC" in sql
    assert "LIMIT" not in sql and "OFFSET" not in sql and filters["author"] not in sql
    assert parameters == tuple(filters.values())
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["layer"] == "db" and event["operation"] == "export"
    assert event["request_id"] == "req-cli-export"

    cursor.fetchall.return_value = []
    assert db.export_records_cli("database-url", {}, "study_date", "desc", "req-cli-empty") == []
    sql, parameters = cursor.execute.call_args.args
    assert "WHERE" not in sql and parameters == ()


def test_export_records_cli_failure_is_logged(monkeypatch, capsys):
    monkeypatch.setattr(db.psycopg, "connect", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        db.export_records_cli("database-url", {}, "title", "asc", "req-cli-export-error")
    event = json.loads(capsys.readouterr().out)
    assert event["client"] == "cli" and event["level"] == "ERROR"
    assert event["request_id"] == "req-cli-export-error"
