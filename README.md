# DiarioDev

Diário de estudos para registrar o aprendizado em desenvolvimento. A issue #1 entrega a página inicial, o login Web e a estrutura da API e do banco. Cadastro e consulta dos registros serão adicionados nas próximas issues.

## Iniciar e entrar (issue #1)

É preciso ter apenas Docker com Docker Compose, navegador e terminal. Todos os comandos abaixo são executados na raiz do projeto.

1. Copie `.env.example` para `.env`. O arquivo `.env` é ignorado pelo Git. Defina `INITIAL_USERNAME` com o usuário desejado.
2. Gere o hash da senha inicial com o contêiner. Digite a senha quando solicitado e copie o resultado completo entre **aspas simples** para `INITIAL_PASSWORD_HASH` em `.env` (por exemplo, `INITIAL_PASSWORD_HASH='scrypt:...'`). As aspas evitam que o Compose interprete os caracteres `$` do hash:

   ```sh
   docker compose run --rm --no-deps api python -c "from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass('Senha inicial: ')))"
   ```

3. Gere dois segredos diferentes e copie os resultados para `SESSION_SECRET` e `POSTGRES_PASSWORD` em `.env`:

   ```sh
   docker compose run --rm --no-deps api python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Execute o comando duas vezes. Não publique `.env` ou a senha digitada.

4. Inicie Web, API e banco:

   ```sh
   docker compose up --build -d
   ```

5. Abra [http://localhost:8080](http://localhost:8080) e entre com `INITIAL_USERNAME` e a senha usada no passo 2. A página mantém a sessão ao recarregar e oferece o botão **Sair**.

O usuário inicial é criado ou atualizado a cada inicialização da API. No banco, a senha é armazenada somente como hash. Alterar `INITIAL_USERNAME` ou `INITIAL_PASSWORD_HASH` em `.env` e reiniciar a API atualiza esse usuário.

## API Web

| Método e rota | Acesso | Resultado |
|---|---|---|
| `GET /api/web/health` | Público | `200`, `{"status":"ok"}` |
| `POST /api/web/login` | Público | Recebe JSON `{"username":"...","password":"..."}`; cria a sessão ou retorna `401` |
| `GET /api/web/me` | Sessão | Retorna o usuário autenticado ou `401` |
| `POST /api/web/logout` | Sessão | Encerra a sessão ou retorna `401` |

O cookie da sessão é `HttpOnly` e `SameSite=Lax`. A página acessa a API pela mesma origem usando o proxy do Nginx. Rotas funcionais adicionadas nas próximas issues também deverão exigir sessão válida.

Para verificar o healthcheck pelo contêiner Web:

```sh
docker compose exec web wget -qO- http://localhost/api/web/health
```

## Banco e logs

PostgreSQL mantém os dados no volume `postgres_data`. A tabela `users` guarda o usuário inicial e seu hash. A tabela `records` está preparada com título, assunto, resumo, data de estudo e minutos estudados para as próximas issues.

As operações Web emitem uma linha JSON por evento no stdout. A API registra healthcheck, inicialização e tentativas de autenticação; `db.py` registra inicialização e consultas de usuário, inclusive falhas. Eventos da API e do banco na mesma requisição têm o mesmo `request_id`. Senhas, hashes, tokens, payloads e SQL não aparecem nos logs.

```sh
docker compose logs -f api
```

## Testes e cobertura

Os testes unitários rodam em contêiner e exigem 100% de cobertura de linhas em `api.py` e `db.py`:

```sh
docker compose run --rm --no-deps tests
```

Para encerrar os serviços sem apagar os dados:

```sh
docker compose down
```
