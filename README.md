# DiarioDev

Diário de estudos para registrar o aprendizado em desenvolvimento. A issue #1 entrega a página inicial e o login Web; a #2 adiciona cadastro e edição de registros; a #7 adiciona a CLI com autenticação por token. Listagem e outras operações de registros virão nas próximas issues.

## Configurar, iniciar e entrar (issue #1)

É preciso ter apenas Docker com Docker Compose, navegador e terminal. Execute todos os comandos na raiz deste worktree ou clone. **Se ainda não existir `.env`**, copie o modelo no PowerShell com `Copy-Item .env.example .env`; em Bash, use `cp .env.example .env`. O `.env` é local e ignorado pelo Git.

1. Defina `INITIAL_USERNAME` no `.env` (o exemplo usa `admin`). Construa a imagem da API antes de usar os comandos de configuração: `docker compose build api`.
2. Gere o hash da senha inicial no contêiner. Digite uma senha escolhida por você quando solicitado e guarde-a para o login. Copie o hash exibido para `INITIAL_PASSWORD_HASH` em `.env`, entre **aspas simples** (por exemplo, `INITIAL_PASSWORD_HASH='scrypt:...'`). As aspas evitam que o Compose interprete os caracteres `$` do hash. Não coloque a senha em texto puro nesse arquivo:

   ```sh
   docker compose run --rm --no-deps api python -c "from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass('Senha inicial: ')))"
   ```

3. Gere dois segredos diferentes e copie os resultados para `SESSION_SECRET` e `POSTGRES_PASSWORD` em `.env`:

   ```sh
   docker compose run --rm --no-deps api python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Execute o comando duas vezes. Os quatro campos de `.env` devem ter valores não vazios. Não publique `.env`, a senha digitada ou os segredos.

4. Inicie Web, API e banco:

   ```sh
   docker compose up --build -d
   ```

5. Confira `docker compose ps`: `web`, `api` e `db` devem aparecer em execução, com API e banco saudáveis. Abra [http://localhost:8080](http://localhost:8080) e entre com `INITIAL_USERNAME` e **a senha digitada no passo 2**, não com o hash. A página mantém a sessão ao recarregar e oferece o botão **Sair**.

O usuário inicial é criado ou atualizado a cada inicialização da API. No banco, a senha é armazenada somente como hash. Alterar `INITIAL_USERNAME` ou `INITIAL_PASSWORD_HASH` em `.env` e reiniciar a API atualiza esse usuário.

Se o banco informar `Database is uninitialized and superuser password is not specified`, preencha `POSTGRES_PASSWORD` em `.env` e execute `docker compose up --build -d` novamente. Para diagnosticar outros problemas, use `docker compose logs --tail 50 db api`.

## API Web

| Método e rota | Acesso | Resultado |
|---|---|---|
| `GET /api/web/health` | Público | `200`, `{"status":"ok"}` |
| `POST /api/web/login` | Público | Recebe JSON `{"username":"...","password":"..."}`; cria a sessão ou retorna `401` |
| `GET /api/web/me` | Sessão | Retorna o usuário autenticado ou `401` |
| `POST /api/web/logout` | Sessão | Encerra a sessão ou retorna `401` |
| `POST /api/web/records` | Sessão | Cria um registro (`201`), ou retorna `400` com `errors` por campo / `401` |
| `PUT /api/web/records/{id}` | Sessão | Edita um registro (`200`), ou retorna `400` / `401` / `404` |
| `PATCH /api/web/records/{id}/status` | Sessão | Recebe `{"status":"active"\|"inactive"}`; retorna o registro (`200`), `400` / `401` / `404` |

O cookie da sessão é `HttpOnly` e `SameSite=Lax`. A página acessa a API pela mesma origem usando o proxy do Nginx. Rotas funcionais adicionadas nas próximas issues também deverão exigir sessão válida.

Para verificar o healthcheck pelo contêiner Web:

```sh
docker compose exec web wget -qO- http://localhost/api/web/health
```

## Cadastro e edição de registros (issue #2)

Depois do login, a página exibe o formulário **Novo registro** com cinco campos, todos obrigatórios:

| Campo | Regra |
|---|---|
| `title` (Título) | Texto, até 120 caracteres |
| `topic` (Assunto) | Texto, até 60 caracteres |
| `summary` (Resumo) | Texto, até 1000 caracteres |
| `study_date` (Data do estudo) | Data válida `AAAA-MM-DD` |
| `minutes` (Minutos estudados) | Inteiro de 0 a 1440 |

Campos inválidos recebem uma mensagem de erro abaixo do próprio campo. A validação ocorre no navegador e novamente na API (`400` com `{"errors": {"campo": "mensagem"}}`). Ao salvar, `POST /api/web/records` grava o registro no PostgreSQL e o formulário passa para o modo **Editar registro #id**: **Salvar alterações** usa `PUT /api/web/records/{id}`. **Novo registro** limpa o formulário. Os dados persistem no volume `postgres_data`.

Exemplo pelo terminal (com a sessão de login em `cookies.txt`):

```sh
curl -c cookies.txt -H 'Content-Type: application/json' -d '{"username":"admin","password":"SUA_SENHA"}' http://localhost:8080/api/web/login
curl -b cookies.txt -H 'Content-Type: application/json' -d '{"title":"Git","topic":"Worktree","summary":"Estudo","study_date":"2026-11-15","minutes":30}' http://localhost:8080/api/web/records
```

Logs: a API registra `create` e `update` (sucesso, validação, não encontrado e falha) e `db.py` registra `insert` e `update`, com o mesmo `request_id`.

## CLI e autenticação (issue #7)

A CLI roda no contêiner `cli` e chama somente a API REST. O serviço inicia a API e o banco quando necessário. Para ver a ajuda e testar o healthcheck público:

```sh
docker compose run --rm cli --help
docker compose run --rm cli health
```

Obtenha um token com o usuário inicial configurado em `.env`. O comando pede a senha sem mostrá-la no terminal:

```sh
docker compose run --rm cli token --username admin
```

Substitua `admin` se configurou outro `INITIAL_USERNAME`. No prompt `Senha:`, digite a mesma senha usada para gerar o hash do usuário inicial. Uma senha incorreta retorna `HTTP 401: Invalid credentials`; uma senha correta imprime o token. Para usá-lo no PowerShell, cole **o token real** quando solicitado:

```powershell
$env:DIARIODEV_TOKEN = (Read-Host 'Cole o token exibido pela CLI').Trim()
docker compose run --rm cli me
```

O resultado esperado é `Usuário: admin` (ou o nome configurado). Copie o token completo, sem espaços ou barras `\` acrescentadas pela formatação de mensagens. Em Bash, use `export DIARIODEV_TOKEN='TOKEN_REAL'` antes de `docker compose run --rm cli me`. O comando `me` usa `Authorization: Bearer <token>`. Sem token ou com token inválido, a API responde `401`; para conferir:

```sh
docker compose run --rm cli --token invalido me
```

O resultado esperado nesse teste é `HTTP 401: Unauthorized` e código de saída 1. O token vence após uma hora; execute `token` novamente para renová-lo. Não publique o token nem o arquivo `.env`. Nesta issue, a CLI oferece apenas `health`, `token` e `me`; comandos para registros pertencem às próximas issues.

Para automações que já fornecem a senha pela entrada padrão, `token --username admin --password-stdin` lê uma linha sem colocar a senha nos argumentos do processo. O modo interativo acima continua sendo o recomendado para uso manual.

| Método e rota | Acesso | Resultado |
|---|---|---|
| `GET /api/cli/health` | Público | `200`, `{"status":"ok"}` |
| `POST /api/cli/token` | Público | Recebe usuário e senha em JSON; retorna `token`, `token_type` e `expires_in`, ou `401` |
| `GET /api/cli/me` | Bearer token | Retorna o usuário autenticado ou `401` |

Os endpoints CLI são separados dos endpoints Web. O token é assinado com `SESSION_SECRET` e não é registrado nos logs. A autenticação por token pode ser reutilizada pelos comandos de registros das próximas issues.


## Status do registro na Web (issue #13)

Todo registro tem um status `active` (padrão) ou `inactive`, salvo na coluna `records.status` (adicionada automaticamente na inicialização da API). Ao editar um registro, a página mostra o status atual e o botão **Ativar/Desativar**, que chama `PATCH /api/web/records/{id}/status` e persiste a mudança no PostgreSQL. As respostas de registros incluem o campo `status`.

```sh
curl -b cookies.txt -X PATCH -H 'Content-Type: application/json' -d '{"status":"inactive"}' http://localhost:8080/api/web/records/1/status
```

Logs: a API registra `status` e `db.py` registra `update_status`, com o mesmo `request_id`.

## Banco e logs

PostgreSQL mantém os dados no volume `postgres_data`. A tabela `users` guarda o usuário inicial e seu hash. A tabela `records` guarda título, assunto, resumo, data de estudo e minutos estudados.

As operações Web e CLI emitem uma linha JSON por evento no stdout. A API registra healthchecks, inicialização e tentativas de autenticação; `db.py` registra inicialização e consultas de usuário, inclusive falhas. Eventos da API e do banco na mesma requisição têm o mesmo `request_id` e identificam `client` como `web` ou `cli`. Senhas, hashes, tokens, payloads e SQL não aparecem nos logs.

```sh
docker compose logs -f api
```

## Testes e cobertura

Os testes unitários rodam em contêiner e exigem 100% de cobertura de linhas em `cli.py`, `api.py` e `db.py`:

```sh
docker compose run --rm --no-deps --build tests
```

Nesta versão, o resultado esperado é **21 testes aprovados e 100% de cobertura**. Para consultar os logs JSON da API e do acesso ao banco, use `docker compose logs -f api`; pressione `Ctrl+C` para parar de acompanhar os logs.

Para encerrar os serviços sem apagar os dados do volume PostgreSQL:

```sh
docker compose down
```

## Commit, push e PR da issue #7

Cada pessoa faz seu commit, push e PR a partir do próprio fork e worktree. Na branch `feat/issue-7-cli-auth`, confira `git status` e prepare apenas os arquivos desta issue; `.env` e `cookies.txt` são ignorados pelo Git:

```sh
git add .gitignore Dockerfile README.md api.py cli.py compose.yaml db.py requirements.txt tests/test_api.py tests/test_cli.py tests/test_db.py
git diff --cached --check
git commit -m "feat: adiciona estrutura e autenticação da CLI"
git push -u origin feat/issue-7-cli-auth
```

No GitHub, abra uma PR com base em `VideoDownloaderPos/DiarioDev:main` e origem `Murilo751/DiarioDev:feat/issue-7-cli-auth`. Preencha `.github/PULL_REQUEST_TEMPLATE.md`, inclua `Closes #7`, descreva as rotas CLI e os logs, e justifique os arquivos auxiliares (`.gitignore`, `Dockerfile`, `compose.yaml`, `requirements.txt` e testes). Informe o comando de testes e a cobertura obtida. Peça a aprovação de todos os colegas antes do merge; a integração no repositório principal deve usar **Rebase and merge**. Após o merge da PR principal, a equipe cria a tag SemVer e a release no commit resultante do `main`.
