import io
import json
import runpy
import sys
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

import cli


def test_duplicate_posts_to_cli_endpoint_and_shows_both_ids(monkeypatch, capsys):
    request_api = MagicMock(return_value=(201, {"id": 18}))
    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    assert cli.main(["duplicate", "17"]) == 0
    request_api.assert_called_once_with("http://api:8000", "/api/cli/records/17/duplicate",
                                        "POST", token="env-token")
    assert capsys.readouterr().out == "Registro #17 duplicado. Novo registro: #18.\n"


@pytest.mark.parametrize("status, message", [
    (401, "Unauthorized"), (404, "Record not found"), (503, "Record unavailable"),
])
def test_duplicate_reports_api_errors(monkeypatch, capsys, status, message):
    monkeypatch.setattr(cli, "call_api", lambda *_, **__: (status, {"error": message}))
    assert cli.main(["duplicate", "17"]) == 1
    output = capsys.readouterr()
    assert output.err == f"HTTP {status}: {message}\n" and output.out == ""


@pytest.mark.parametrize("arguments", [["duplicate"], ["duplicate", "abc"]])
def test_duplicate_requires_integer_id(arguments):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


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


def test_dashboard_prints_three_indicators_from_cli_endpoint(monkeypatch, capsys):
    calls = []

    def request_api(*args, **kwargs):
        calls.append((args, kwargs))
        return 200, {
            "by_category": [{"label": "Git", "total": 3}],
            "by_author": [{"label": "student", "total": 4}],
            "by_month": [{"label": "2026-11", "total": 4}],
        }

    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    assert cli.main(["dashboard"]) == 0
    assert calls == [(("http://api:8000", "/api/cli/dashboard"), {"token": "env-token"})]
    assert capsys.readouterr().out.splitlines() == [
        "Por categoria:", "  Git: 3", "Por autor:", "  student: 4", "Por mês:", "  2026-11: 4",
    ]


def test_dashboard_empty_and_unauthorized(monkeypatch, capsys):
    monkeypatch.setattr(cli, "call_api", lambda *_args, **_kwargs: (200, {
        "by_category": [], "by_author": [], "by_month": [],
    }))
    assert cli.main(["dashboard"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Por categoria:", "  (sem dados)", "Por autor:", "  (sem dados)",
        "Por mês:", "  (sem dados)",
    ]
    monkeypatch.setattr(cli, "call_api", lambda *_args, **_kwargs: (401, {"error": "Unauthorized"}))
    assert cli.main(["dashboard"]) == 1
    assert "HTTP 401" in capsys.readouterr().err


def test_create_and_edit_send_records_only_to_api(monkeypatch, capsys):
    calls = []

    def request_api(*args, **kwargs):
        calls.append((args, kwargs))
        return (201 if args[2] == "POST" else 200), {"id": 17}

    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    fields = ["--title", "Git", "--topic", "Worktree", "--summary", "Estudo",
              "--study-date", "2026-11-15", "--minutes", "30"]
    assert cli.main(["create", *fields]) == 0
    assert cli.main(["edit", "17", *fields]) == 0
    payload = {"title": "Git", "topic": "Worktree", "summary": "Estudo",
               "study_date": "2026-11-15", "minutes": 30}
    assert calls == [
        (("http://api:8000", "/api/cli/records", "POST", payload, "env-token"), {}),
        (("http://api:8000", "/api/cli/records/17", "PUT", payload, "env-token"), {}),
    ]
    assert capsys.readouterr().out.splitlines() == [
        "Registro #17 criado.", "Registro #17 atualizado.",
    ]


def test_record_commands_report_api_validation_and_auth_errors(monkeypatch, capsys):
    fields = ["--title", "Git", "--topic", "Worktree", "--summary", "Estudo",
              "--study-date", "2026-11-15", "--minutes", "30"]
    monkeypatch.setattr(cli, "call_api", lambda *_args, **_kwargs: (400, {
        "errors": {"study_date": "Informe uma data válida", "minutes": "Valor inválido"},
    }))
    assert cli.main(["create", *fields]) == 1
    assert capsys.readouterr().err.splitlines() == [
        "study_date: Informe uma data válida", "minutes: Valor inválido",
    ]
    monkeypatch.setattr(cli, "call_api", lambda *_args, **_kwargs: (401, {"error": "Unauthorized"}))
    assert cli.main(["edit", "17", *fields]) == 1
    assert "HTTP 401: Unauthorized" in capsys.readouterr().err


def test_list_and_delete_call_only_the_cli_api(monkeypatch, capsys):
    calls = []

    def request_api(*args, **kwargs):
        calls.append((args, kwargs))
        if len(args) > 2 and args[2] == "DELETE":
            return 200, {"id": 17, "deleted": True}
        return 200, {"items": [{"id": 17, "study_date": "2026-11-15", "title": "Git",
                                "topic": "Worktree", "minutes": 30}],
                     "page": 2, "page_size": 3, "total": 4, "total_pages": 2}

    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    assert cli.main(["list", "--page", "2", "--page-size", "3", "--sort", "title",
                     "--direction", "asc"]) == 0
    assert cli.main(["list"]) == 0
    assert cli.main(["delete", "17"]) == 0
    assert calls[0] == (("http://api:8000",
                         "/api/cli/records?page=2&page_size=3&sort=title&direction=asc"), {"token": "env-token"})
    assert calls[1][0][1] == "/api/cli/records?page=1&page_size=5&sort=study_date&direction=desc"
    assert calls[2] == (("http://api:8000", "/api/cli/records/17", "DELETE"), {"token": "env-token"})
    assert capsys.readouterr().out.splitlines() == [
        "#17 | 2026-11-15 | Git | Worktree | 30 min", "Página 2 de 2 (4 registros)",
        "#17 | 2026-11-15 | Git | Worktree | 30 min", "Página 2 de 2 (4 registros)",
        "Registro #17 excluído.",
    ]


def test_list_and_delete_report_api_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (404, {"error": "Record not found"}))
    assert cli.main(["delete", "99"]) == 1
    assert "HTTP 404: Record not found" in capsys.readouterr().err
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (401, {"error": "Unauthorized"}))
    assert cli.main(["list"]) == 1
    assert "HTTP 401" in capsys.readouterr().err


def test_status_command_calls_only_the_cli_endpoint(monkeypatch, capsys):
    calls = []

    def request_api(*args, **kwargs):
        calls.append((args, kwargs))
        return 200, {"id": 17, "status": args[3]["status"]}

    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    assert cli.main(["status", "17", "inactive"]) == 0
    assert cli.main(["status", "17", "active"]) == 0
    assert calls[0] == (("http://api:8000", "/api/cli/records/17/status", "PATCH",
                         {"status": "inactive"}, "env-token"), {})
    assert capsys.readouterr().out.splitlines() == ["Registro #17: inativo.", "Registro #17: ativo."]


def test_status_command_reports_api_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (404, {"error": "Record not found"}))
    assert cli.main(["status", "99", "active"]) == 1
    assert "HTTP 404: Record not found" in capsys.readouterr().err
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (401, {"error": "Unauthorized"}))
    assert cli.main(["status", "1", "active"]) == 1
    assert "HTTP 401" in capsys.readouterr().err
    with pytest.raises(SystemExit) as result:
        cli.main(["status", "1", "paused"])
    assert result.value.code == 2


def test_search_sends_only_given_filters_to_the_cli_api(monkeypatch, capsys):
    calls = []

    def request_api(*args, **kwargs):
        calls.append((args, kwargs))
        return 200, {"items": [{"id": 3, "study_date": "2026-11-15", "title": "Git",
                                "topic": "Worktree", "minutes": 30}],
                     "page": 1, "page_size": 5, "total": 1, "total_pages": 1}

    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    assert cli.main(["search", "--author", "admin", "--category", "work",
                     "--date-from", "2026-11-01", "--date-to", "2026-11-30",
                     "--page", "2", "--page-size", "4", "--sort", "title", "--direction", "asc"]) == 0
    assert cli.main(["search"]) == 0
    assert calls[0] == (("http://api:8000", "/api/cli/records/search?page=2&page_size=4&sort=title"
                         "&direction=asc&author=admin&category=work&date_from=2026-11-01"
                         "&date_to=2026-11-30"), {"token": "env-token"})
    assert calls[1][0][1] == "/api/cli/records/search?page=1&page_size=5&sort=study_date&direction=desc"
    assert capsys.readouterr().out.splitlines() == [
        "#3 | 2026-11-15 | Git | Worktree | 30 min", "Página 1 de 1 (1 registros)",
        "#3 | 2026-11-15 | Git | Worktree | 30 min", "Página 1 de 1 (1 registros)",
    ]


def test_search_reports_invalid_parameters_and_auth_errors(monkeypatch, capsys):
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (400, {"error": "Invalid search parameters"}))
    assert cli.main(["search", "--date-from", "ruim"]) == 1
    assert "HTTP 400: Invalid search parameters" in capsys.readouterr().err
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (401, {"error": "Unauthorized"}))
    assert cli.main(["search"]) == 1
    assert "HTTP 401" in capsys.readouterr().err


def test_call_api_raw_returns_bytes(monkeypatch):
    monkeypatch.setattr(cli, "urlopen", lambda _request, timeout: Response(b"id,title\r\n"))
    assert cli.call_api("http://api:8000", "/api/cli/records/export", raw=True) == (200, b"id,title\r\n")


def test_export_writes_csv_with_filters(monkeypatch, capsys, tmp_path):
    calls = []
    content = "\ufeffid,title\r\n1,Git\r\n2,\"Linha 1\nLinha 2\"\r\n".encode("utf-8")

    def request_api(*args, **kwargs):
        calls.append((args, kwargs))
        return 200, content

    monkeypatch.setattr(cli, "call_api", request_api)
    monkeypatch.setenv("DIARIODEV_TOKEN", "env-token")
    target = tmp_path / "saida.csv"
    assert cli.main(["export", "--author", "student", "--category", "Git", "--date-from", "2026-11-01",
                     "--date-to", "2026-11-30", "--sort", "title", "--direction", "asc",
                     "--output", str(target)]) == 0
    assert calls[0] == (("http://api:8000", "/api/cli/records/export?sort=title&direction=asc"
                         "&author=student&category=Git&date_from=2026-11-01&date_to=2026-11-30"),
                        {"token": "env-token", "raw": True})
    assert target.read_bytes() == content
    assert capsys.readouterr().out == f"2 registros exportados para {target}.\n"
    assert cli.main(["export", "--output", str(target)]) == 0
    assert calls[1][0][1] == "/api/cli/records/export?sort=study_date&direction=desc"


def test_export_reports_api_and_file_errors(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (400, {"errors": {"date_from": "Data inválida"}}))
    assert cli.main(["export", "--output", str(tmp_path / "x.csv")]) == 1
    assert "date_from: Data inválida" in capsys.readouterr().err
    assert not (tmp_path / "x.csv").exists()
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (401, {"error": "Unauthorized"}))
    assert cli.main(["export"]) == 1
    assert "HTTP 401" in capsys.readouterr().err
    monkeypatch.setattr(cli, "call_api", lambda *_a, **_k: (200, b"id\r\n"))
    assert cli.main(["export", "--output", str(tmp_path / "pasta" / "x.csv")]) == 1
    assert "Não foi possível gravar" in capsys.readouterr().err


def test_module_entrypoint_shows_help(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--help"])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("cli", run_name="__main__")
    assert result.value.code == 0
