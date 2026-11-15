"""Web authentication and record endpoints for DiarioDev."""

import json
import os
from datetime import date, datetime, timezone
from functools import wraps
from uuid import uuid4

from flask import Flask, g, jsonify, request, session
from werkzeug.security import check_password_hash

import db


def log_event(level, operation, status, request_id, message):
    print(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level,
        "layer": "api",
        "client": "web",
        "operation": operation,
        "status": status,
        "request_id": request_id,
        "message": message,
    }), flush=True)


TEXT_LIMITS = {"title": 120, "topic": 60, "summary": 1000}


def validate_record(body):
    """Return (clean record, errors) for the five required diary fields."""
    if not isinstance(body, dict):
        body = {}
    record, errors = {}, {}
    for field, limit in TEXT_LIMITS.items():
        value = body.get(field)
        value = value.strip() if isinstance(value, str) else ""
        if not value:
            errors[field] = "Campo obrigatório"
        elif len(value) > limit:
            errors[field] = f"Máximo de {limit} caracteres"
        else:
            record[field] = value
    study_date = body.get("study_date")
    try:
        if not isinstance(study_date, str) or not study_date:
            raise ValueError
        record["study_date"] = date.fromisoformat(study_date)
    except ValueError:
        errors["study_date"] = "Informe uma data válida (AAAA-MM-DD)"
    minutes = body.get("minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= 1440:
        errors["minutes"] = "Informe um número inteiro de 0 a 1440"
    else:
        record["minutes"] = minutes
    return record, errors


def serialize_record(row):
    return {
        "id": row[0], "title": row[1], "topic": row[2], "summary": row[3],
        "study_date": row[4].isoformat(), "minutes": row[5],
    }


def create_app(config=None, initialize=True):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SESSION_SECRET", ""),
        DATABASE_URL=os.getenv("DATABASE_URL", ""),
        INITIAL_USERNAME=os.getenv("INITIAL_USERNAME", "admin"),
        INITIAL_PASSWORD_HASH=os.getenv("INITIAL_PASSWORD_HASH", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)
    if initialize:
        if not all(app.config[key] for key in (
            "SECRET_KEY", "DATABASE_URL", "INITIAL_USERNAME", "INITIAL_PASSWORD_HASH"
        )):
            raise RuntimeError("Configure SESSION_SECRET, DATABASE_URL and initial user credentials")
        request_id = str(uuid4())
        try:
            db.initialize(
                app.config["DATABASE_URL"],
                app.config["INITIAL_USERNAME"],
                app.config["INITIAL_PASSWORD_HASH"],
                request_id,
            )
            log_event("INFO", "initialize", "success", request_id, "Web API ready")
        except Exception:
            log_event("ERROR", "initialize", "error", request_id, "Web API initialization failed")
            raise

    @app.before_request
    def assign_request_id():
        g.request_id = str(uuid4())

    def login_required(operation):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if "user_id" not in session:
                    log_event("WARN", operation, "error", g.request_id, "Authentication required")
                    return jsonify(error="Unauthorized"), 401
                return view(*args, **kwargs)
            return wrapped
        return decorator

    @app.get("/api/web/health")
    def health():
        log_event("INFO", "health", "success", g.request_id, "Web API healthy")
        return jsonify(status="ok")

    @app.post("/api/web/login")
    def login():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            log_event("WARN", "login", "error", g.request_id, "Invalid credentials")
            return jsonify(error="Invalid credentials"), 401
        try:
            user = db.get_user(app.config["DATABASE_URL"], username, g.request_id)
        except Exception:
            log_event("ERROR", "login", "error", g.request_id, "Login unavailable")
            return jsonify(error="Login unavailable"), 503
        if not user or not check_password_hash(user[2], password):
            log_event("WARN", "login", "error", g.request_id, "Invalid credentials")
            return jsonify(error="Invalid credentials"), 401
        session.clear()
        session["user_id"] = user[0]
        session["username"] = user[1]
        log_event("INFO", "login", "success", g.request_id, "User authenticated")
        return jsonify(username=user[1])

    @app.get("/api/web/me")
    @login_required("me")
    def me():
        log_event("INFO", "me", "success", g.request_id, "Session inspected")
        return jsonify(username=session["username"])

    @app.post("/api/web/logout")
    @login_required("logout")
    def logout():
        session.clear()
        log_event("INFO", "logout", "success", g.request_id, "User signed out")
        return jsonify(status="ok")

    @app.post("/api/web/records")
    @login_required("create")
    def create_record():
        record, errors = validate_record(request.get_json(silent=True))
        if errors:
            log_event("WARN", "create", "error", g.request_id, "Invalid record")
            return jsonify(errors=errors), 400
        try:
            row = db.create_record(app.config["DATABASE_URL"], record, g.request_id)
        except Exception:
            log_event("ERROR", "create", "error", g.request_id, "Record creation failed")
            return jsonify(error="Record unavailable"), 503
        log_event("INFO", "create", "success", g.request_id, "Registro criado")
        return jsonify(serialize_record(row)), 201

    @app.put("/api/web/records/<int:record_id>")
    @login_required("update")
    def update_record(record_id):
        record, errors = validate_record(request.get_json(silent=True))
        if errors:
            log_event("WARN", "update", "error", g.request_id, "Invalid record")
            return jsonify(errors=errors), 400
        try:
            row = db.update_record(app.config["DATABASE_URL"], record_id, record, g.request_id)
        except Exception:
            log_event("ERROR", "update", "error", g.request_id, "Record update failed")
            return jsonify(error="Record unavailable"), 503
        if row is None:
            log_event("WARN", "update", "error", g.request_id, "Record not found")
            return jsonify(error="Record not found"), 404
        log_event("INFO", "update", "success", g.request_id, "Registro atualizado")
        return jsonify(serialize_record(row))

    return app
