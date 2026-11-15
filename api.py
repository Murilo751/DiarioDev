"""Web authentication and record endpoints for DiarioDev."""

import json
import os
from datetime import date, datetime, timezone
from functools import wraps
from uuid import uuid4

from flask import Flask, g, jsonify, request, session
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

import db


def log_event(level, operation, status, request_id, message, client="web"):
    print(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level,
        "layer": "api",
        "client": client,
        "operation": operation,
        "status": status,
        "request_id": request_id,
        "message": message,
    }), flush=True)


STATUSES = ("active", "inactive")
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
        "study_date": row[4].isoformat(), "minutes": row[5], "status": row[6],
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
    token_signer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="diariodev-cli")
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

    def cli_auth_required(operation):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                authorization = request.headers.get("Authorization", "")
                if not authorization.startswith("Bearer "):
                    log_event("WARN", operation, "error", g.request_id,
                              "CLI authentication required", "cli")
                    return jsonify(error="Unauthorized"), 401
                try:
                    g.cli_user = token_signer.loads(authorization[7:], max_age=3600)
                except BadSignature:
                    log_event("WARN", operation, "error", g.request_id,
                              "Invalid CLI token", "cli")
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

    @app.get("/api/cli/health")
    def cli_health():
        log_event("INFO", "health", "success", g.request_id, "CLI API healthy", "cli")
        return jsonify(status="ok")

    @app.post("/api/cli/token")
    def cli_token():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            log_event("WARN", "token", "error", g.request_id, "Invalid credentials", "cli")
            return jsonify(error="Invalid credentials"), 401
        try:
            user = db.get_user(app.config["DATABASE_URL"], username, g.request_id, "cli")
        except Exception:
            log_event("ERROR", "token", "error", g.request_id, "Token service unavailable", "cli")
            return jsonify(error="Token service unavailable"), 503
        if not user or not check_password_hash(user[2], password):
            log_event("WARN", "token", "error", g.request_id, "Invalid credentials", "cli")
            return jsonify(error="Invalid credentials"), 401
        token = token_signer.dumps({"id": user[0], "username": user[1]})
        log_event("INFO", "token", "success", g.request_id, "CLI user authenticated", "cli")
        return jsonify(token=token, token_type="Bearer", expires_in=3600)

    @app.get("/api/cli/me")
    @cli_auth_required("me")
    def cli_me():
        log_event("INFO", "me", "success", g.request_id, "CLI token accepted", "cli")
        return jsonify(username=g.cli_user["username"])


    @app.patch("/api/web/records/<int:record_id>/status")
    @login_required("status")
    def change_status(record_id):
        body = request.get_json(silent=True)
        status = body.get("status") if isinstance(body, dict) else None
        if status not in STATUSES:
            log_event("WARN", "status", "error", g.request_id, "Invalid status")
            return jsonify(errors={"status": "Use active ou inactive"}), 400
        try:
            row = db.update_status(app.config["DATABASE_URL"], record_id, status, g.request_id)
        except Exception:
            log_event("ERROR", "status", "error", g.request_id, "Record status update failed")
            return jsonify(error="Record unavailable"), 503
        if row is None:
            log_event("WARN", "status", "error", g.request_id, "Record not found")
            return jsonify(error="Record not found"), 404
        log_event("INFO", "status", "success", g.request_id, "Status do registro atualizado")
        return jsonify(serialize_record(row))

    return app
