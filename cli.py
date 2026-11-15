"""Command-line client for the DiarioDev REST API."""

import argparse
import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def call_api(base_url, path, method="GET", payload=None, token=None):
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def main(argv=None):
    parser = argparse.ArgumentParser(description="CLI do DiarioDev")
    parser.add_argument("--api-url", default=os.getenv("DIARIODEV_API_URL", "http://api:8000"),
                        help="URL da API (padrão: http://api:8000)")
    parser.add_argument("--token", default=os.getenv("DIARIODEV_TOKEN"),
                        help="Token Bearer; também aceita DIARIODEV_TOKEN")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="Verificar a API da CLI")
    token_command = commands.add_parser("token", help="Obter token de acesso")
    token_command.add_argument("--username", required=True, help="Usuário inicial configurado")
    token_command.add_argument("--password-stdin", action="store_true",
                               help="Ler a senha da entrada padrão")
    commands.add_parser("me", help="Verificar o token e mostrar o usuário")
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
    delete_command = commands.add_parser("delete", help="Excluir um registro pelo identificador")
    delete_command.add_argument("id", type=int, help="Identificador do registro")
    args = parser.parse_args(argv)

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
        elif args.command == "list":
            query = urlencode({"page": args.page, "page_size": args.page_size,
                               "sort": args.sort, "direction": args.direction})
            status, result = call_api(args.api_url, f"/api/cli/records?{query}", token=args.token)
        elif args.command == "delete":
            status, result = call_api(args.api_url, f"/api/cli/records/{args.id}", "DELETE",
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

    if status != (201 if args.command == "create" else 200):
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
    elif args.command == "list":
        for item in result["items"]:
            print(f"#{item['id']} | {item['study_date']} | {item['title']} | "
                  f"{item['topic']} | {item['minutes']} min")
        print(f"Página {result['page']} de {result['total_pages']} "
              f"({result['total']} registros)")
    elif args.command == "delete":
        print(f"Registro #{result['id']} excluído.")
    elif args.command == "create":
        print(f"Registro #{result['id']} criado.")
    else:
        print(f"Registro #{result['id']} atualizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
