"""Behavior checks for interactive terminal sessions and recovery paths."""

import builtins
from datetime import date
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

import cli


RECORD = {"id": 17, "title": "Revisão de Git", "topic": "Git", "summary": "Branches e worktrees",
          "study_date": "2026-11-16", "minutes": 30, "status": "active"}
CSV = "\ufeffid,title\r\n17,Revisão de Git\r\n".encode("utf-8")


def inputs(monkeypatch, values):
    remaining = iter(values)
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        return next(remaining)

    monkeypatch.setattr(builtins, "input", read)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "test-only-password")
    return prompts


def api_stub(monkeypatch, items=None, total_pages=1, interceptor=None):
    calls = []
    items = [dict(RECORD)] if items is None else items

    def request(base, path, method="GET", payload=None, token=None, raw=False):
        calls.append((path, method, payload, token, raw))
        if interceptor:
            overridden = interceptor(path, method, payload, token)
            if overridden is not None:
                return overridden
        if path == "/api/cli/token":
            return 200, {"token": "test-session"}
        if path == "/api/cli/me":
            return 200, {"username": "student"}
        if path.startswith("/api/cli/records/export?"):
            return 200, CSV
        if path == "/api/cli/dashboard":
            return 200, {"by_category": [{"label": "Git", "total": 2}],
                         "by_author": [{"label": "student", "total": 2}], "by_month": []}
        if method == "GET":
            page = int(parse_qs(urlsplit(path).query).get("page", ["1"])[0])
            return 200, {"items": items, "page": page, "total_pages": total_pages,
                         "total": len(items) * total_pages}
        return (201 if method == "POST" else 200), {**RECORD, "id": 18}

    monkeypatch.setattr(cli, "call_api", request)
    return calls


def test_form_checks_values_and_preserves_existing_fields(monkeypatch, capsys):
    inputs(monkeypatch, ["", "x" * 121, "Novo título", "Git", "Resumo", "inválida",
                         "2026-02-30", "2026-11-16", "abc", "-1", "1441", "0"])
    created = cli.menu_form()
    assert created == {"title": "Novo título", "topic": "Git", "summary": "Resumo",
                       "study_date": "2026-11-16", "minutes": 0}
    output = capsys.readouterr().out
    assert "Campo obrigatório" in output and "Informe uma data válida" in output
    assert "número inteiro de 0 a 1440" in output
    inputs(monkeypatch, ["", "", "", "", "45"])
    assert cli.menu_form(RECORD) == {**{key: RECORD[key] for key in created}, "minutes": 45}
    inputs(monkeypatch, ["Git", "Git", "Resumo", "", "30"])
    assert cli.menu_form()["study_date"] == date.today().isoformat()


def test_menu_input_cancellation_and_option_retry(monkeypatch, capsys):
    inputs(monkeypatch, ["  :voltar  "])
    with pytest.raises(cli.MenuCancelled):
        cli.menu_input("Título")
    inputs(monkeypatch, ["99", "1"])
    assert cli.menu_choice("Opção", ("0", "1")) == "1"
    assert "Opção inválida" in capsys.readouterr().out


@pytest.mark.parametrize("status, body, expected", [
    (400, {"errors": {"date_to": "Período invertido"}}, "date_to: Período invertido"),
    (401, {"error": "Unauthorized"}, "Sessão inválida"),
    (404, {"error": "missing"}, "Registro não encontrado"),
    (503, {"error": "offline"}, "Serviço indisponível"),
    (500, {"error": "Unexpected response"}, "Unexpected response"),
    (500, {}, "Falha na API"),
])
def test_api_failures_have_actionable_messages(monkeypatch, status, body, expected):
    monkeypatch.setattr(cli, "call_api", lambda *args, **kwargs: (status, body))
    with pytest.raises(cli.MenuError, match=expected) as error:
        cli.menu_request("http://api:8000", "test-session", "/api/cli/records")
    assert error.value.status == status


@pytest.mark.parametrize("error", [URLError("offline"), TimeoutError("timeout"),
                                  ConnectionResetError("reset")])
def test_transport_errors_are_not_reported_as_csv_failures(monkeypatch, error):
    def unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, "call_api", unavailable)
    with pytest.raises(cli.MenuError, match="conectar à API"):
        cli.menu_request("http://api:8000", "test-session", "/api/cli/records")


def test_invalid_login_explains_credentials_instead_of_expiration(monkeypatch):
    monkeypatch.setattr(cli, "call_api", lambda *args, **kwargs: (401, {"error": "Invalid credentials"}))
    with pytest.raises(cli.MenuError, match="Usuário ou senha inválidos"):
        cli.menu_request("http://api:8000", None, "/api/cli/token", "POST", {})


@pytest.mark.parametrize("arguments", [[], ["menu"]])
def test_login_and_exit_keep_token_inside_session(monkeypatch, capsys, arguments):
    monkeypatch.delenv("DIARIODEV_TOKEN", raising=False)
    calls = api_stub(monkeypatch)
    inputs(monkeypatch, ["student", "0"])
    assert cli.main(arguments) == 0
    assert calls[0] == ("/api/cli/token", "POST", {"username": "student", "password": "test-only-password"}, None, False)
    assert all(call[3] == "test-session" for call in calls[1:])
    out = capsys.readouterr().out
    assert "DIARIODEV" in out and "Até a próxima" in out
    assert "test-session" not in out and "test-only-password" not in out
    assert "DIARIODEV_TOKEN" not in __import__("os").environ


def test_create_then_edit_through_real_menu_dispatch(monkeypatch, capsys):
    calls = api_stub(monkeypatch)
    inputs(monkeypatch, ["1", "Novo estudo", "Python", "Resumo", "2026-11-16", "20",
                         "2", "17", "1", "", "", "", "", "45", "0"])
    assert cli.main(["--token", "test-session", "menu"]) == 0
    writes = [call for call in calls if call[1] in ("POST", "PUT")]
    assert writes[0][:3] == ("/api/cli/records", "POST", {
        "title": "Novo estudo", "topic": "Python", "summary": "Resumo",
        "study_date": "2026-11-16", "minutes": 20})
    assert writes[1][:3] == ("/api/cli/records/17", "PUT", {
        **{key: RECORD[key] for key in ("title", "topic", "summary", "study_date")}, "minutes": 45})
    assert "Estudo #18 criado" in capsys.readouterr().out


@pytest.mark.parametrize("action, confirmation, status, method, suffix, payload", [
    ("2", [], "active", "PATCH", "/status", {"status": "inactive"}),
    ("2", [], "inactive", "PATCH", "/status", {"status": "active"}),
    ("3", [], "active", "POST", "/duplicate", None),
    ("4", ["s"], "active", "DELETE", "", None),
])
def test_record_actions_use_cli_routes(monkeypatch, capsys, action, confirmation, status, method, suffix, payload):
    calls = api_stub(monkeypatch)
    inputs(monkeypatch, ["17", action, *confirmation])
    cli.menu_record("http://api:8000", "test-session", [{**RECORD, "status": status}])
    assert calls == [("/api/cli/records/17" + suffix, method, payload, "test-session", False)]
    assert "Resumo:" in capsys.readouterr().out


@pytest.mark.parametrize("answers", [["999"], ["17", "0"], ["17", "4", "n"]])
def test_missing_record_back_and_declined_delete_do_not_write(monkeypatch, answers):
    calls = api_stub(monkeypatch)
    inputs(monkeypatch, answers)
    cli.menu_record("http://api:8000", "test-session", [RECORD])
    assert calls == []


def test_filters_sort_export_dashboard_and_pagination(monkeypatch, capsys, tmp_path):
    calls = api_stub(monkeypatch, total_pages=2)
    target = tmp_path / "filtrados.csv"
    inputs(monkeypatch, ["3", "1", "student", "Git", "2026-11-01", "2026-11-30",
                         "4", "2", "1", "8", "7", "5", str(target), "6", "",
                         "3", "0", "3", "2", "0"])
    assert cli.main(["--token", "test-session"]) == 0
    exported = next(call for call in calls if "/export?" in call[0])
    query = parse_qs(urlsplit(exported[0]).query)
    assert query == {"author": ["student"], "category": ["Git"], "date_from": ["2026-11-01"],
                     "date_to": ["2026-11-30"], "sort": ["title"], "direction": ["asc"]}
    assert exported[4] is True and target.read_bytes() == CSV
    pages = [parse_qs(urlsplit(call[0]).query).get("page") for call in calls if call[1] == "GET"]
    assert ["2"] in pages
    output = capsys.readouterr().out
    assert "Filtros aplicados" in output and "Filtros limpos" in output
    assert "Estudos por assunto" in output and "Sem dados" in output


def test_filter_empty_fields_and_failed_validation_preserve_old_filters(monkeypatch):
    calls = api_stub(monkeypatch)
    inputs(monkeypatch, ["1", "", "Git", "", ""])
    assert cli.menu_filters("http://api:8000", "test-session", {}, "minutes", "desc") == {"category": "Git"}
    old = {"category": "Python"}
    inputs(monkeypatch, ["1", "", "Git", "bad-date", ""])
    monkeypatch.setattr(cli, "call_api", lambda *args, **kwargs: (400, {"errors": {"date_from": "Data inválida"}}))
    with pytest.raises(cli.MenuError):
        cli.menu_filters("http://api:8000", "test-session", old, "minutes", "desc")
    assert old == {"category": "Python"} and calls


def test_logout_starts_a_fresh_login_and_cancellation_exits(monkeypatch, capsys):
    calls = api_stub(monkeypatch)
    inputs(monkeypatch, ["4", "4", "2", "9", ":voltar"])
    assert cli.main(["--token", "test-session"]) == 0
    assert "Você saiu da conta" in capsys.readouterr().out
    assert sum(call[0] == "/api/cli/me" for call in calls) == 1


def test_cancelling_a_form_returns_to_studies(monkeypatch, capsys):
    calls = api_stub(monkeypatch, items=[])
    inputs(monkeypatch, ["1", ":voltar", "0"])
    assert cli.main(["--token", "test-session"]) == 0
    assert not any(call[1] == "POST" for call in calls)
    output = capsys.readouterr().out
    assert "Operação cancelada" in output and "Nenhum estudo encontrado" in output


def test_expired_token_and_invalid_password_can_be_retried(monkeypatch, capsys):
    rejected = []

    def reject_once(path, method, payload, token):
        if (path == "/api/cli/me" or path == "/api/cli/token") and path not in rejected:
            rejected.append(path)
            return 401, {"error": "Unauthorized"}

    calls = api_stub(monkeypatch, interceptor=reject_once)
    inputs(monkeypatch, ["student", "student", "0"])
    assert cli.main(["--token", "expired"]) == 0
    output = capsys.readouterr().out
    assert "Sessão inválida" in output and "Usuário ou senha inválidos" in output
    assert calls[-1][3] == "test-session"


def test_service_error_before_list_recovers_after_enter(monkeypatch, capsys):
    failures = []

    def unavailable_once(path, method, payload, token):
        if path.startswith("/api/cli/records?") and not failures:
            failures.append(path)
            return 503, {}

    api_stub(monkeypatch, interceptor=unavailable_once)
    inputs(monkeypatch, ["", "0"])
    assert cli.main(["--token", "test-session"]) == 0
    assert "Serviço indisponível" in capsys.readouterr().out


def test_api_failure_during_action_returns_to_menu(monkeypatch, capsys):
    def unavailable(path, method, payload, token):
        if path == "/api/cli/dashboard":
            return 503, {}

    api_stub(monkeypatch, interceptor=unavailable)
    inputs(monkeypatch, ["6", "0"])
    assert cli.main(["--token", "test-session"]) == 0
    assert "Serviço indisponível" in capsys.readouterr().out


def test_deleted_last_page_returns_to_existing_page(monkeypatch):
    counts = []

    def shrink(path, method, payload, token):
        if path.startswith("/api/cli/records?"):
            page = int(parse_qs(urlsplit(path).query)["page"][0])
            counts.append(page)
            return 200, {"items": [RECORD], "page": page, "total": 1,
                         "total_pages": 2 if len(counts) == 1 else 1}

    api_stub(monkeypatch, interceptor=shrink)
    inputs(monkeypatch, ["8", "0"])
    assert cli.main(["--token", "test-session"]) == 0
    assert counts == [1, 2, 1]


def test_csv_write_failure_does_not_end_session(monkeypatch, capsys, tmp_path):
    api_stub(monkeypatch)
    inputs(monkeypatch, ["5", str(tmp_path / "missing" / "file.csv"), "0"])
    assert cli.main(["--token", "test-session"]) == 0
    assert "Não foi possível gravar o CSV" in capsys.readouterr().out


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_interrupt_or_end_of_input_closes_without_traceback(monkeypatch, capsys, error):
    monkeypatch.delenv("DIARIODEV_TOKEN", raising=False)

    def interrupted(prompt):
        raise error

    monkeypatch.setattr(builtins, "input", interrupted)
    assert cli.main(["menu"]) == 0
    assert "Sessão encerrada" in capsys.readouterr().out


def test_cancel_after_initial_connection_failure_closes_session(monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(cli, "call_api", unavailable)
    inputs(monkeypatch, [":voltar"])
    assert cli.main(["--token", "test-session"]) == 0
    assert "Sessão encerrada" in capsys.readouterr().out
