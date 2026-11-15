"""Database schema, user lookups and record persistence for Web and CLI."""

import json
from datetime import datetime, timezone

import psycopg


def log_event(level, client, operation, status, request_id, message):
    print(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level,
        "layer": "db",
        "client": client,
        "operation": operation,
        "status": status,
        "request_id": request_id,
        "message": message,
    }), flush=True)


def initialize(database_url, username, password_hash, request_id):
    """Create the schema and keep the configured initial user up to date."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS records (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        title TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        study_date DATE NOT NULL,
                        minutes INTEGER NOT NULL CHECK (minutes >= 0),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cursor.execute(
                    "ALTER TABLE records ADD COLUMN IF NOT EXISTS status TEXT NOT NULL "
                    "DEFAULT 'active' CHECK (status IN ('active', 'inactive'))"
                )
                cursor.execute("ALTER TABLE records ADD COLUMN IF NOT EXISTS author TEXT")
                cursor.execute("UPDATE records SET author = %s WHERE author IS NULL", (username,))
                cursor.execute("ALTER TABLE records ALTER COLUMN author SET NOT NULL")
                cursor.execute("""
                    INSERT INTO users (id, username, password_hash)
                    VALUES (1, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        username = EXCLUDED.username,
                        password_hash = EXCLUDED.password_hash
                """, (username, password_hash))
        log_event("INFO", "web", "initialize", "success", request_id, "Schema and initial user ready")
    except Exception:
        log_event("ERROR", "web", "initialize", "error", request_id, "Database initialization failed")
        raise


def get_user(database_url, username, request_id, client="web"):
    """Read a user for login without logging credentials or password hashes."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, username, password_hash FROM users WHERE username = %s",
                    (username,),
                )
                user = cursor.fetchone()
        log_event("INFO", client, "get_user", "success", request_id, "User lookup completed")
        return user
    except Exception:
        log_event("ERROR", client, "get_user", "error", request_id, "User lookup failed")
        raise


RECORD_COLUMNS = "id, title, topic, summary, study_date, minutes, status"
SORT_COLUMNS = {"study_date": "study_date", "title": "title", "topic": "topic", "minutes": "minutes"}


def create_record(database_url, record, request_id):
    """Insert a study record and return the stored row."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO records (title, topic, summary, study_date, minutes, author) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING " + RECORD_COLUMNS,
                    (record["title"], record["topic"], record["summary"],
                     record["study_date"], record["minutes"], record["author"]),
                )
                row = cursor.fetchone()
        log_event("INFO", "web", "insert", "success", request_id, "Record persisted")
        return row
    except Exception:
        log_event("ERROR", "web", "insert", "error", request_id, "Record insert failed")
        raise


def update_record(database_url, record_id, record, request_id):
    """Update a study record and return the stored row, or None when it does not exist."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE records SET title = %s, topic = %s, summary = %s, "
                    "study_date = %s, minutes = %s WHERE id = %s RETURNING " + RECORD_COLUMNS,
                    (record["title"], record["topic"], record["summary"],
                     record["study_date"], record["minutes"], record_id),
                )
                row = cursor.fetchone()
        log_event("INFO", "web", "update", "success", request_id,
                  "Record updated" if row else "Record not found")
        return row
    except Exception:
        log_event("ERROR", "web", "update", "error", request_id, "Record update failed")
        raise


def list_records(database_url, page, sort, direction, request_id):
    """Return a stable five-item page and the total number of records."""
    order_column = SORT_COLUMNS[sort]
    order_direction = "ASC" if direction == "asc" else "DESC"
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM records")
                total = cursor.fetchone()[0]
                cursor.execute(
                    f"SELECT {RECORD_COLUMNS} FROM records "
                    f"ORDER BY {order_column} {order_direction}, id DESC LIMIT %s OFFSET %s",
                    (5, (page - 1) * 5),
                )
                rows = cursor.fetchall()
        log_event("INFO", "web", "list", "success", request_id, "Records listed")
        return rows, total
    except Exception:
        log_event("ERROR", "web", "list", "error", request_id, "Record listing failed")
        raise


def search_records(database_url, filters, page, sort, direction, request_id):
    """Search with independent SQL and combine all provided Web filters."""
    conditions, values = [], []
    if filters["author"]:
        conditions.append("LOWER(author) = LOWER(%s)")
        values.append(filters["author"])
    if filters["category"]:
        conditions.append("STRPOS(LOWER(topic), LOWER(%s)) > 0")
        values.append(filters["category"])
    if filters["date_from"]:
        conditions.append("study_date >= %s")
        values.append(filters["date_from"])
    if filters["date_to"]:
        conditions.append("study_date <= %s")
        values.append(filters["date_to"])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_column = SORT_COLUMNS[sort]
    order_direction = "ASC" if direction == "asc" else "DESC"
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM records" + where, values)
                total = cursor.fetchone()[0]
                cursor.execute(
                    f"SELECT {RECORD_COLUMNS} FROM records{where} "
                    f"ORDER BY {order_column} {order_direction}, id DESC LIMIT %s OFFSET %s",
                    (*values, 5, (page - 1) * 5),
                )
                rows = cursor.fetchall()
        log_event("INFO", "web", "search", "success", request_id, "Records searched")
        return rows, total
    except Exception:
        log_event("ERROR", "web", "search", "error", request_id, "Record search failed")
        raise


def export_records(database_url, filters, sort, direction, request_id):
    """Read all matching Web records with a dedicated query and no LIMIT/OFFSET."""
    conditions, parameters = [], []
    if filters.get("author"):
        conditions.append("LOWER(author) = LOWER(%s)")
        parameters.append(filters["author"])
    if filters.get("category"):
        conditions.append("STRPOS(LOWER(topic), LOWER(%s)) > 0")
        parameters.append(filters["category"])
    if "date_from" in filters:
        conditions.append("study_date >= %s")
        parameters.append(filters["date_from"])
    if "date_to" in filters:
        conditions.append("study_date <= %s")
        parameters.append(filters["date_to"])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_column = SORT_COLUMNS[sort]
    order_direction = "ASC" if direction == "asc" else "DESC"
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {RECORD_COLUMNS} FROM records{where} "
                    f"ORDER BY {order_column} {order_direction}, id DESC",
                    tuple(parameters),
                )
                rows = cursor.fetchall()
        log_event("INFO", "web", "export", "success", request_id, "Records read for CSV export")
        return rows
    except Exception:
        log_event("ERROR", "web", "export", "error", request_id, "Record export query failed")
        raise


def delete_record(database_url, record_id, request_id):
    """Delete one record and report whether it existed."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM records WHERE id = %s RETURNING id", (record_id,))
                deleted = cursor.fetchone() is not None
        log_event("INFO" if deleted else "WARN", "web", "delete",
                  "success" if deleted else "error", request_id,
                  "Record deleted" if deleted else "Record not found")
        return deleted
    except Exception:
        log_event("ERROR", "web", "delete", "error", request_id, "Record deletion failed")
        raise


def update_status(database_url, record_id, status, request_id):
    """Set a record's status and return the stored row, or None when it does not exist."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE records SET status = %s WHERE id = %s RETURNING " + RECORD_COLUMNS,
                    (status, record_id),
                )
                row = cursor.fetchone()
        log_event("INFO", "web", "update_status", "success", request_id,
                  "Record status updated" if row else "Record not found")
        return row
    except Exception:
        log_event("ERROR", "web", "update_status", "error", request_id, "Record status update failed")
        raise


def create_record_cli(database_url, record, request_id):
    """Insert a record requested through the CLI endpoint."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO records (title, topic, summary, study_date, minutes, author) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING " + RECORD_COLUMNS,
                    (record["title"], record["topic"], record["summary"],
                     record["study_date"], record["minutes"], record["author"]),
                )
                row = cursor.fetchone()
        log_event("INFO", "cli", "insert", "success", request_id, "Record persisted")
        return row
    except Exception:
        log_event("ERROR", "cli", "insert", "error", request_id, "Record insert failed")
        raise


def update_record_cli(database_url, record_id, record, request_id):
    """Update a record requested through the CLI endpoint."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE records SET title = %s, topic = %s, summary = %s, "
                    "study_date = %s, minutes = %s WHERE id = %s RETURNING " + RECORD_COLUMNS,
                    (record["title"], record["topic"], record["summary"],
                     record["study_date"], record["minutes"], record_id),
                )
                row = cursor.fetchone()
        if row is None:
            log_event("WARN", "cli", "update", "error", request_id, "Record not found")
        else:
            log_event("INFO", "cli", "update", "success", request_id, "Record updated")
        return row
    except Exception:
        log_event("ERROR", "cli", "update", "error", request_id, "Record update failed")
        raise


def list_records_cli(database_url, page, page_size, sort, direction, request_id):
    """Return a page of records and the total, requested through the CLI endpoint."""
    order_column = SORT_COLUMNS[sort]
    order_direction = "ASC" if direction == "asc" else "DESC"
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM records")
                total = cursor.fetchone()[0]
                cursor.execute(
                    f"SELECT {RECORD_COLUMNS} FROM records "
                    f"ORDER BY {order_column} {order_direction}, id DESC LIMIT %s OFFSET %s",
                    (page_size, (page - 1) * page_size),
                )
                rows = cursor.fetchall()
        log_event("INFO", "cli", "list", "success", request_id, "Records listed")
        return rows, total
    except Exception:
        log_event("ERROR", "cli", "list", "error", request_id, "Record listing failed")
        raise


def delete_record_cli(database_url, record_id, request_id):
    """Delete one record requested through the CLI endpoint and report whether it existed."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM records WHERE id = %s RETURNING id", (record_id,))
                deleted = cursor.fetchone() is not None
        log_event("INFO" if deleted else "WARN", "cli", "delete",
                  "success" if deleted else "error", request_id,
                  "Record deleted" if deleted else "Record not found")
        return deleted
    except Exception:
        log_event("ERROR", "cli", "delete", "error", request_id, "Record deletion failed")
        raise


def update_status_cli(database_url, record_id, status, request_id):
    """Set a record's status requested through the CLI endpoint."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE records SET status = %s WHERE id = %s RETURNING " + RECORD_COLUMNS,
                    (status, record_id),
                )
                row = cursor.fetchone()
        if row is None:
            log_event("WARN", "cli", "update_status", "error", request_id, "Record not found")
        else:
            log_event("INFO", "cli", "update_status", "success", request_id, "Record status updated")
        return row
    except Exception:
        log_event("ERROR", "cli", "update_status", "error", request_id, "Record status update failed")
        raise


def search_records_cli(database_url, filters, page, page_size, sort, direction, request_id):
    """Search with SQL of its own for the CLI, combining every provided filter."""
    conditions, values = [], []
    if filters["author"]:
        conditions.append("LOWER(author) = LOWER(%s)")
        values.append(filters["author"])
    if filters["category"]:
        conditions.append("STRPOS(LOWER(topic), LOWER(%s)) > 0")
        values.append(filters["category"])
    if filters["date_from"]:
        conditions.append("study_date >= %s")
        values.append(filters["date_from"])
    if filters["date_to"]:
        conditions.append("study_date <= %s")
        values.append(filters["date_to"])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_column = SORT_COLUMNS[sort]
    order_direction = "ASC" if direction == "asc" else "DESC"
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM records" + where, values)
                total = cursor.fetchone()[0]
                cursor.execute(
                    f"SELECT {RECORD_COLUMNS} FROM records{where} "
                    f"ORDER BY {order_column} {order_direction}, id DESC LIMIT %s OFFSET %s",
                    (*values, page_size, (page - 1) * page_size),
                )
                rows = cursor.fetchall()
        log_event("INFO", "cli", "search", "success", request_id, "Records searched")
        return rows, total
    except Exception:
        log_event("ERROR", "cli", "search", "error", request_id, "Record search failed")
        raise


def duplicate_record(database_url, record_id, author, request_id):
    """Insert a copy of a record (new ID, current author) and return it, or None when missing."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO records (title, topic, summary, study_date, minutes, status, author) "
                    "SELECT title, topic, summary, study_date, minutes, status, %s "
                    "FROM records WHERE id = %s RETURNING " + RECORD_COLUMNS,
                    (author, record_id),
                )
                row = cursor.fetchone()
        if row is None:
            log_event("WARN", "web", "duplicate", "error", request_id, "Record not found")
        else:
            log_event("INFO", "web", "duplicate", "success", request_id, "Record duplicated")
        return row
    except Exception:
        log_event("ERROR", "web", "duplicate", "error", request_id, "Record duplication failed")
        raise
