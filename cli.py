"""Command-line client for the DiarioDev REST API."""

import argparse
import csv
import getpass
import io
import json
import os
import sys
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MenuError(Exception):
    """An API failure that can be displayed without ending the terminal session."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class MenuCancelled(Exception):
    """Return from a form to the studies screen."""


def menu_input(label, default=None):
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{label}{suffix}: ").strip()
    if value == ":voltar":
        raise MenuCancelled
    return str(default) if not value and default is not None else value


def menu_choice(label, choices):
    while True:
        value = menu_input(label)
        if value in choices:
            return value
        print("Opção inválida. Escolha uma das opções exibidas.")


def menu_request(api_url, token, path, method="GET", payload=None, raw=False):
    try:
        status, result = call_api(api_url, path, method, payload, token, raw=raw)
    except (URLError, TimeoutError, ConnectionError):
        raise MenuError("Não foi possível conectar à API. Confira se os serviços estão iniciados.") from None
    if status not in (200, 201):
        messages = {401: "Sessão inválida ou expirada. Entre novamente.",
                    404: "Registro não encontrado. Atualize a lista e tente novamente.",
                    503: "Serviço indisponível. Tente novamente em instantes."}
        if path == "/api/cli/token":
            messages[401] = "Usuário ou senha inválidos. Confira suas credenciais."
        detail = "; ".join(f"{key}: {value}" for key, value in result.get("errors", {}).items())
        raise MenuError(detail or messages.get(status, result.get("error", "Falha na API")), status)
    return result


def menu_form(record=None):
    print("\nEDITAR ESTUDO" if record else "\nADICIONAR ESTUDO")
    print("Digite :voltar para cancelar. Na edição, Enter mantém o valor atual.")
    record = record or {}
    payload = {}
    for key, label, limit in (("title", "Título", 120), ("topic", "Assunto", 60),
                              ("summary", "Resumo", 1000)):
        while True:
            value = menu_input(label, record.get(key))
            if value and len(value) <= limit:
                payload[key] = value
                break
            print(f"Campo obrigatório, com até {limit} caracteres.")
    while True:
        value = menu_input("Data do estudo (AAAA-MM-DD)", record.get("study_date", date.today().isoformat()))
        try:
            payload["study_date"] = date.fromisoformat(value).isoformat()
            break
        except ValueError:
            print("Informe uma data válida no formato AAAA-MM-DD.")
    while True:
        value = menu_input("Minutos estudados (0 a 1440)", record.get("minutes"))
        try:
            minutes = int(value)
            if not 0 <= minutes <= 1440:
                raise ValueError
            payload["minutes"] = minutes
            return payload
        except ValueError:
            print("Informe um número inteiro de 0 a 1440.")


def menu_table(result, username, filters, sort, direction):
    print("\n" + "═" * 88)
    print(f"  DIARIODEV  /  ESTUDOS                                    Usuário: {username}")
    print("═" * 88)
    print("Filtros: " + (" | ".join(f"{key}={value}" for key, value in filters.items()) or "nenhum"))
    labels = {"study_date": "data", "title": "título", "topic": "assunto", "minutes": "minutos"}
    print(f"Ordenação: {labels[sort]} ({'crescente' if direction == 'asc' else 'decrescente'})")
    print(f"{'ID':<6} {'Título':<26} {'Assunto':<19} {'Data':<12} {'Minutos':>7}  Status")
    print("─" * 88)
    for item in result["items"]:
        title = " ".join(item["title"].split())[:25]
        topic = " ".join(item["topic"].split())[:18]
        status = "Ativo" if item["status"] == "active" else "Inativo"
        print(f"{item['id']:<6} {title:<26} {topic:<19} {item['study_date']:<12} "
              f"{item['minutes']:>7}  {status}")
    if not result["items"]:
        print("Nenhum estudo encontrado. Adicione um estudo ou ajuste os filtros.")
    print(f"\nPágina {result['page']} de {max(1, result['total_pages'])} | {result['total']} estudos")
    print("\n[1] Adicionar estudo    [2] Abrir estudo        [3] Filtros / limpar")
    print("[4] Ordenar             [5] Exportar CSV       [6] Dashboard")
    print("[7] Página anterior     [8] Próxima página     [9] Sair da conta")
    print("[0] Encerrar")


def menu_record(api_url, token, items):
    record_id = menu_input("ID do estudo desta página (:voltar para cancelar)")
    record = next((item for item in items if str(item["id"]) == record_id), None)
    if record is None:
        print("Escolha o ID de um estudo exibido na página atual.")
        return
    print(f"\nESTUDO #{record['id']} — {record['title']}")
    print(f"Assunto: {record['topic']} | Data: {record['study_date']} | {record['minutes']} min")
    print(f"Status: {'Ativo' if record['status'] == 'active' else 'Inativo'}\nResumo: {record['summary']}")
    print("\n[1] Editar  [2] Ativar/desativar  [3] Duplicar  [4] Excluir  [0] Voltar")
    choice = menu_choice("Ação", ("0", "1", "2", "3", "4"))
    path = f"/api/cli/records/{record['id']}"
    if choice == "1":
        menu_request(api_url, token, path, "PUT", menu_form(record))
        print("Estudo atualizado. A alteração também está disponível na Web.")
    elif choice == "2":
        status = "inactive" if record["status"] == "active" else "active"
        menu_request(api_url, token, path + "/status", "PATCH", {"status": status})
        print("Status atualizado.")
    elif choice == "3":
        result = menu_request(api_url, token, path + "/duplicate", "POST")
        print(f"Estudo duplicado. Novo registro: #{result['id']}. Original preservado.")
    elif choice == "4":
        if menu_choice("Excluir definitivamente? [s] Sim / [n] Não", ("s", "n")) == "s":
            menu_request(api_url, token, path, "DELETE")
            print("Estudo excluído.")


def menu_filters(api_url, token, filters, sort, direction):
    print("\nFILTROS  [1] Aplicar filtros  [2] Limpar filtros  [0] Voltar")
    choice = menu_choice("Ação", ("0", "1", "2"))
    if choice == "0":
        return filters
    candidate = {}
    if choice == "1":
        print("Deixe vazio para não filtrar pelo campo. Digite :voltar para cancelar.")
        for key, label in (("author", "Autor"), ("category", "Assunto"),
                           ("date_from", "Data inicial (AAAA-MM-DD)"),
                           ("date_to", "Data final (AAAA-MM-DD)")):
            value = menu_input(label)
            if value:
                candidate[key] = value
        query = urlencode(dict(candidate, sort=sort, direction=direction))
        menu_request(api_url, token, "/api/cli/records/search?" + query)
    print("Filtros aplicados." if candidate else "Filtros limpos.")
    return candidate


def menu_dashboard(api_url, token):
    result = menu_request(api_url, token, "/api/cli/dashboard")
    print("\nDIARIODEV / DASHBOARD")
    for title, key in (("Estudos por assunto", "by_category"),
                       ("Estudos por autor", "by_author"), ("Estudos por mês", "by_month")):
        print(f"\n{title}")
        maximum = max((item["total"] for item in result[key]), default=1)
        for item in result[key]:
            bar = "█" * max(1, round(item["total"] / max(1, maximum) * 24))
            print(f"  {item['label']:<24} {bar} {item['total']}")
        if not result[key]:
            print("  Sem dados.")
    menu_input("Enter para voltar aos estudos")


def interactive_menu(api_url, token=None):
    username, filters, page, sort, direction = "", {}, 1, "study_date", "desc"
    print("\nDIARIODEV — Seu diário de estudos no terminal")
    print("Use os números do menu. Nos formulários, :voltar cancela; Ctrl+C encerra.")
    while True:
        choice = None
        try:
            if not token:
                print("\nENTRAR  (digite :voltar no usuário para encerrar)")
                login = menu_input("Usuário")
                password = getpass.getpass("Senha: ")
                result = menu_request(api_url, None, "/api/cli/token", "POST",
                                      {"username": login, "password": password})
                token = result["token"]
            if not username:
                username = menu_request(api_url, token, "/api/cli/me")["username"]
            query = urlencode(dict(filters, page=page, page_size=5, sort=sort, direction=direction))
            endpoint = "/api/cli/records/search" if filters else "/api/cli/records"
            result = menu_request(api_url, token, endpoint + "?" + query)
            if page > max(1, result["total_pages"]):
                page = max(1, result["total_pages"])
                continue
            menu_table(result, username, filters, sort, direction)
            choice = menu_choice("Escolha", tuple(str(number) for number in range(10)))
            if choice == "0":
                print("Até a próxima!")
                return 0
            if choice == "1":
                created = menu_request(api_url, token, "/api/cli/records", "POST", menu_form())
                print(f"Estudo #{created['id']} criado. Confira também na Web.")
            elif choice == "2":
                menu_record(api_url, token, result["items"])
            elif choice == "3":
                filters = menu_filters(api_url, token, filters, sort, direction)
                page = 1
            elif choice == "4":
                print("\nORDENAR  [1] Data  [2] Título  [3] Assunto  [4] Minutos")
                selected = menu_choice("Campo", ("1", "2", "3", "4"))
                new_sort = {"1": "study_date", "2": "title", "3": "topic", "4": "minutes"}[selected]
                selected = menu_choice("Direção [1] Crescente / [2] Decrescente", ("1", "2"))
                sort, direction, page = new_sort, "asc" if selected == "1" else "desc", 1
            elif choice == "5":
                output_path = menu_input("Nome do arquivo CSV", "registros.csv")
                query = urlencode(dict(filters, sort=sort, direction=direction))
                content = menu_request(api_url, token, "/api/cli/records/export?" + query, raw=True)
                with open(output_path, "wb") as output:
                    output.write(content)
                print(f"CSV salvo em {output_path} no contêiner, com todos os resultados filtrados.")
                print("Para copiar ao computador, em outro terminal: docker compose cp cli:/app/ARQUIVO ./ARQUIVO")
            elif choice == "6":
                menu_dashboard(api_url, token)
            elif choice in ("7", "8"):
                page = max(1, page - 1) if choice == "7" else min(max(1, result["total_pages"]), page + 1)
            elif choice == "9":
                token, username, filters, page, sort, direction = None, "", {}, 1, "study_date", "desc"
                print("Você saiu da conta.")
        except MenuCancelled:
            if not token:
                return 0
            print("Operação cancelada.")
        except MenuError as error:
            print(f"\n{error}")
            if error.status == 401:
                token, username = None, ""
            elif choice is None:
                menu_input("Enter para tentar novamente; :voltar para encerrar")
        except OSError:
            print("Não foi possível gravar o CSV. Confira o caminho e as permissões.")


def call_api(base_url, path, method="GET", payload=None, token=None, raw=False):
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read() if raw else json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def main(argv=None):
    parser = argparse.ArgumentParser(description="CLI do DiarioDev")
    parser.add_argument("--api-url", default=os.getenv("DIARIODEV_API_URL", "http://api:8000"),
                        help="URL da API (padrão: http://api:8000)")
    parser.add_argument("--token", default=os.getenv("DIARIODEV_TOKEN"),
                        help="Token Bearer; também aceita DIARIODEV_TOKEN")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("menu", help="Abrir o menu interativo de estudos e dashboard")
    commands.add_parser("health", help="Verificar a API da CLI")
    token_command = commands.add_parser("token", help="Obter token de acesso")
    token_command.add_argument("--username", required=True, help="Usuário inicial configurado")
    token_command.add_argument("--password-stdin", action="store_true",
                               help="Ler a senha da entrada padrão")
    commands.add_parser("me", help="Verificar o token e mostrar o usuário")
    commands.add_parser("dashboard", help="Mostrar contagens por categoria, autor e mês")
    for name, help_text in (("create", "Criar um registro"), ("edit", "Editar um registro")):
        command = commands.add_parser(name, help=help_text)
        if name == "edit":
            command.add_argument("id", type=int, help="Identificador do registro")
        command.add_argument("--title", required=True, help="Título (até 120 caracteres)")
        command.add_argument("--topic", required=True, help="Assunto (até 60 caracteres)")
        command.add_argument("--summary", required=True, help="Resumo (até 1000 caracteres)")
        command.add_argument("--study-date", required=True, help="Data do estudo (AAAA-MM-DD)")
        command.add_argument("--minutes", required=True, type=int,
                             help="Minutos estudados (0 a 1440)")
    list_command = commands.add_parser("list", help="Listar registros com paginação e ordenação")
    list_command.add_argument("--page", type=int, default=1, help="Página (a partir de 1)")
    list_command.add_argument("--page-size", type=int, default=5, help="Itens por página (1 a 50)")
    list_command.add_argument("--sort", default="study_date",
                              choices=("study_date", "title", "topic", "minutes"),
                              help="Campo de ordenação (padrão: study_date)")
    list_command.add_argument("--direction", default="desc", choices=("asc", "desc"),
                              help="Direção da ordenação (padrão: desc)")
    search_command = commands.add_parser("search", help="Buscar registros com filtros combináveis")
    search_command.add_argument("--author", help="Autor do registro (usuário que o criou)")
    search_command.add_argument("--category", help="Categoria: trecho do assunto (topic)")
    search_command.add_argument("--date-from", help="Data inicial do estudo, inclusiva (AAAA-MM-DD)")
    search_command.add_argument("--date-to", help="Data final do estudo, inclusiva (AAAA-MM-DD)")
    search_command.add_argument("--page", type=int, default=1, help="Página (a partir de 1)")
    search_command.add_argument("--page-size", type=int, default=5, help="Itens por página (1 a 50)")
    search_command.add_argument("--sort", default="study_date",
                                choices=("study_date", "title", "topic", "minutes"),
                                help="Campo de ordenação (padrão: study_date)")
    search_command.add_argument("--direction", default="desc", choices=("asc", "desc"),
                                help="Direção da ordenação (padrão: desc)")
    export_command = commands.add_parser("export", help="Exportar registros filtrados em CSV")
    export_command.add_argument("--author", help="Autor do registro (usuário que o criou)")
    export_command.add_argument("--category", help="Categoria: trecho do assunto (topic)")
    export_command.add_argument("--date-from", help="Data inicial do estudo, inclusiva (AAAA-MM-DD)")
    export_command.add_argument("--date-to", help="Data final do estudo, inclusiva (AAAA-MM-DD)")
    export_command.add_argument("--sort", default="study_date",
                                choices=("study_date", "title", "topic", "minutes"),
                                help="Campo de ordenação (padrão: study_date)")
    export_command.add_argument("--direction", default="desc", choices=("asc", "desc"),
                                help="Direção da ordenação (padrão: desc)")
    export_command.add_argument("--output", default="registros.csv",
                                help="Arquivo CSV a gravar (padrão: registros.csv)")
    delete_command = commands.add_parser("delete", help="Excluir um registro pelo identificador")
    delete_command.add_argument("id", type=int, help="Identificador do registro")
    duplicate_command = commands.add_parser("duplicate", help="Duplicar um registro com novo ID")
    duplicate_command.add_argument("id", type=int, help="Identificador do registro original")
    status_command = commands.add_parser("status", help="Ativar ou desativar um registro")
    status_command.add_argument("id", type=int, help="Identificador do registro")
    status_command.add_argument("status", choices=("active", "inactive"),
                                help="Novo status: active (ativo) ou inactive (inativo)")
    args = parser.parse_args(argv)

    if args.command in (None, "menu"):
        try:
            return interactive_menu(args.api_url, args.token)
        except (EOFError, KeyboardInterrupt, MenuCancelled):
            print("\nSessão encerrada.")
            return 0

    try:
        if args.command == "health":
            status, result = call_api(args.api_url, "/api/cli/health")
        elif args.command == "token":
            password = (sys.stdin.readline().rstrip("\r\n") if args.password_stdin
                        else getpass.getpass("Senha: "))
            status, result = call_api(args.api_url, "/api/cli/token", "POST",
                                      {"username": args.username, "password": password})
        elif args.command == "me":
            status, result = call_api(args.api_url, "/api/cli/me", token=args.token)
        elif args.command == "dashboard":
            status, result = call_api(args.api_url, "/api/cli/dashboard", token=args.token)
        elif args.command == "list":
            query = urlencode({"page": args.page, "page_size": args.page_size,
                               "sort": args.sort, "direction": args.direction})
            status, result = call_api(args.api_url, f"/api/cli/records?{query}", token=args.token)
        elif args.command == "search":
            query = {"page": args.page, "page_size": args.page_size,
                     "sort": args.sort, "direction": args.direction}
            for name in ("author", "category", "date_from", "date_to"):
                if getattr(args, name):
                    query[name] = getattr(args, name)
            status, result = call_api(args.api_url, f"/api/cli/records/search?{urlencode(query)}",
                                      token=args.token)
        elif args.command == "export":
            query = {"sort": args.sort, "direction": args.direction}
            for name in ("author", "category", "date_from", "date_to"):
                if getattr(args, name):
                    query[name] = getattr(args, name)
            status, result = call_api(args.api_url, f"/api/cli/records/export?{urlencode(query)}",
                                      token=args.token, raw=True)
        elif args.command == "delete":
            status, result = call_api(args.api_url, f"/api/cli/records/{args.id}", "DELETE",
                                      token=args.token)
        elif args.command == "status":
            status, result = call_api(args.api_url, f"/api/cli/records/{args.id}/status", "PATCH",
                                      {"status": args.status}, args.token)
        elif args.command == "duplicate":
            status, result = call_api(args.api_url, f"/api/cli/records/{args.id}/duplicate", "POST",
                                      token=args.token)
        else:
            payload = {
                "title": args.title, "topic": args.topic, "summary": args.summary,
                "study_date": args.study_date, "minutes": args.minutes,
            }
            if args.command == "create":
                status, result = call_api(args.api_url, "/api/cli/records", "POST",
                                          payload, args.token)
            else:
                status, result = call_api(args.api_url, f"/api/cli/records/{args.id}", "PUT",
                                          payload, args.token)
    except URLError:
        print("Não foi possível conectar à API.", file=sys.stderr)
        return 1

    if status != (201 if args.command in ("create", "duplicate") else 200):
        if "errors" in result:
            for field, message in result["errors"].items():
                print(f"{field}: {message}", file=sys.stderr)
        else:
            print(f"HTTP {status}: {result.get('error', 'Falha na API')}", file=sys.stderr)
        return 1
    if args.command == "health":
        print("API da CLI saudável.")
    elif args.command == "token":
        print(result["token"])
    elif args.command == "me":
        print(f"Usuário: {result['username']}")
    elif args.command == "dashboard":
        for title, key in (("Por categoria", "by_category"),
                           ("Por autor", "by_author"), ("Por mês", "by_month")):
            print(f"{title}:")
            if not result[key]:
                print("  (sem dados)")
            for item in result[key]:
                print(f"  {item['label']}: {item['total']}")
    elif args.command in ("list", "search"):
        for item in result["items"]:
            print(f"#{item['id']} | {item['study_date']} | {item['title']} | "
                  f"{item['topic']} | {item['minutes']} min")
        print(f"Página {result['page']} de {result['total_pages']} "
              f"({result['total']} registros)")
    elif args.command == "export":
        try:
            with open(args.output, "wb") as output:
                output.write(result)
        except OSError as error:
            print(f"Não foi possível gravar {args.output}: {error.strerror}", file=sys.stderr)
            return 1
        total = sum(1 for _ in csv.reader(io.StringIO(result.decode("utf-8-sig")))) - 1
        print(f"{total} registros exportados para {args.output}.")
    elif args.command == "delete":
        print(f"Registro #{result['id']} excluído.")
    elif args.command == "status":
        print(f"Registro #{result['id']}: {'ativo' if result['status'] == 'active' else 'inativo'}.")
    elif args.command == "create":
        print(f"Registro #{result['id']} criado.")
    elif args.command == "duplicate":
        print(f"Registro #{args.id} duplicado. Novo registro: #{result['id']}.")
    else:
        print(f"Registro #{result['id']} atualizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
