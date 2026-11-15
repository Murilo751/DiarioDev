import io
import json
import runpy
import sys
from urllib.error import HTTPError, URLError

import pytest

import cli


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_call_api_sends_json_and_bearer_token(monkeypatch):
    def open_request(request, timeout):
        assert request.full_url == "http://api:8000/api/cli/token"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer secret"
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data) == {"username": "student"}
        assert timeout == 10
        return Response(b'{"token":"new-token"}')

    monkeypatch.setattr(cli, "urlopen", open_request)
    assert cli.call_api("http://api:8000/", "/api/cli/token", "POST",
                        {"username": "student"}, "secret") == (200, {"token": "new-token"})


def test_call_api_returns_http_error(monkeypatch):
    def open_request(_request, timeout):
        assert timeout == 10
        raise HTTPError("http://api:8000/api/cli/me", 401, "Unauthorized", None,
                        io.BytesIO(b'{"error":"Unauthorized"}'))

    monkeypatch.setattr(cli, "urlopen", open_request)
    assert cli.call_api("http://api:8000", "/api/cli/me") == (401, {"error": "Unauthorized"})


def test_main_health_token_and_me(monkeypatch, capsys):
    calls = []

    def request_api(*args, **kwargs):
        calls.append((args, kwargs))
        if args[1].endswith("/health"):
            return 200, {"status": "ok"}
        if args[1].endswith("/token"):
            return 200, {"token": "new-token"}
        return 200, {"username": "student"}

    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: "password")
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    assert cli.main(["health"]) == 0
    assert cli.main(["token", "--username", "student"]) == 0
    assert calls[1][0][3] == {"username": "student", "password": "password"}
    monkeypatch.setattr(sys, "stdin", io.StringIO("password-from-stdin\r\n"))
    assert cli.main(["token", "--username", "student", "--password-stdin"]) == 0
    assert calls[2][0][3] == {"username": "student", "password": "password-from-stdin"}
    assert cli.main(["me"]) == 0
    assert calls[3][1]["token"] == "env-token"
    assert cli.main(["--token", "arg-token", "me"]) == 0
    assert calls[4][1]["token"] == "arg-token"
    assert capsys.readouterr().out.splitlines() == [
        "API da CLI saudável.", "new-token", "new-token", "Usuário: student", "Usuário: student",
    ]


def test_main_reports_unauthorized_and_connection_failure(monkeypatch, capsys):
    monkeypatch.setattr(cli, "call_api", lambda *_args, **_kwargs: (401, {"error": "Unauthorized"}))
    assert cli.main(["me"]) == 1
    assert "HTTP 401" in capsys.readouterr().err

    def unavailable(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(cli, "call_api", unavailable)
    assert cli.main(["health"]) == 1
    assert "conectar" in capsys.readouterr().err


def test_module_entrypoint_shows_help(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--help"])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("cli", run_name="__main__")
    assert result.value.code == 0
