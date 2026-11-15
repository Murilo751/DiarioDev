"""Command-line client for the DiarioDev REST API."""

import argparse
import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
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
    args = parser.parse_args(argv)

    try:
        if args.command == "health":
            status, result = call_api(args.api_url, "/api/cli/health")
        elif args.command == "token":
            password = (sys.stdin.readline().rstrip("\r\n") if args.password_stdin
                        else getpass.getpass("Senha: "))
            status, result = call_api(args.api_url, "/api/cli/token", "POST",
                                      {"username": args.username, "password": password})
        else:
            status, result = call_api(args.api_url, "/api/cli/me", token=args.token)
    except URLError:
        print("Não foi possível conectar à API.", file=sys.stderr)
        return 1

    if status != 200:
        print(f"HTTP {status}: {result.get('error', 'Falha na API')}", file=sys.stderr)
        return 1
    if args.command == "health":
        print("API da CLI saudável.")
    elif args.command == "token":
        print(result["token"])
    else:
        print(f"Usuário: {result['username']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
