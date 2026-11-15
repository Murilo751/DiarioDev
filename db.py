"""Database schema and user lookups for the Web API."""

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


def get_user(database_url, username, request_id):
    """Read a user for login without logging credentials or password hashes."""
    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, username, password_hash FROM users WHERE username = %s",
                    (username,),
                )
                user = cursor.fetchone()
        log_event("INFO", "web", "get_user", "success", request_id, "User lookup completed")
        return user
    except Exception:
        log_event("ERROR", "web", "get_user", "error", request_id, "User lookup failed")
        raise
