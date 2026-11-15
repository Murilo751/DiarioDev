# DiarioDev

Diário de estudos para registrar o aprendizado em desenvolvimento. A issue #1 entrega a página inicial e o login Web; a #2 adiciona cadastro e edição; a #3 adiciona listagem e exclusão; a #4 adiciona busca avançada na Web; a #7 adiciona autenticação por token na CLI; a #8 permite criar e editar registros pela CLI; a #9 permite listar e excluir registros pela CLI; a #14 permite alterar o status pela CLI.

## Rodar o sistema pela primeira vez

Você precisa de Docker com Docker Compose (no Windows, Docker Desktop) e um navegador. Inicie o Docker e execute os comandos abaixo **na pasta do projeto**, onde está `compose.yaml`. Confira se o Docker está pronto com `docker info`.

1. Crie o arquivo local de configuração. No PowerShell:

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   ```

   No Bash, use `test -f .env || cp .env.example .env`. Se `.env` já existe, mantenha-o: ele pode conter a senha do banco usada por um volume PostgreSQL anterior.

2. Construa a imagem da API, necessária para gerar o hash e os segredos:

   ```sh
   docker compose build api
   ```

3. Escolha a senha do usuário inicial. O comando pede a senha sem exibi-la e imprime somente o hash:

   ```sh
   docker compose run --rm --no-deps api python -c "from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass('Senha inicial: ')))"
   ```

   Abra `.env`, mantenha `INITIAL_USERNAME=admin` (ou escolha outro nome) e cole o hash em `INITIAL_PASSWORD_HASH` **entre aspas simples**. Exemplo: `INITIAL_PASSWORD_HASH='scrypt:...'`. As aspas impedem que o Compose interprete os caracteres `$` do hash. Guarde a senha digitada: é ela que você usará para entrar, não o hash.

4. Gere um segredo para `SESSION_SECRET` e outro, **diferente**, para `POSTGRES_PASSWORD`. Execute o mesmo comando duas vezes e cole cada resultado na linha correspondente do `.env`:

   ```sh
   docker compose run --rm --no-deps api python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Confira que os quatro campos de `.env` têm valores. Não coloque a senha inicial em texto puro no arquivo nem publique `.env`; ele é ignorado pelo Git.

5. Inicie a página Web, a API, o banco e o contêiner da CLI com um único comando:

   ```sh
   docker compose up --build -d
   docker compose ps
   ```

   `web`, `api`, `db` e `cli` devem estar em execução; `api` e `db` devem aparecer como `healthy`. Abra [http://localhost:8080](http://localhost:8080) e entre com `INITIAL_USERNAME` e a senha escolhida no passo 3. Para conferir a API, execute `docker compose exec web wget -qO- http://localhost/api/web/health`; o resultado esperado é `{"status":"ok"}`.

Nas próximas vezes, use `docker compose up -d` para iniciar e `docker compose down` para parar. `down` preserva os registros no volume PostgreSQL. O usuário inicial é criado ou atualizado a cada inicialização da API; se você alterar `INITIAL_USERNAME` ou `INITIAL_PASSWORD_HASH`, execute `docker compose up -d` novamente.

### Se não iniciar

- Se `docker info` falhar, abra o Docker Desktop e aguarde o mecanismo de contêineres iniciar.
- Se a API apresentar `password authentication failed for user "diariodev"`, o volume do banco já existia com outra senha. Reutilize o `POSTGRES_PASSWORD` antigo no `.env` se souber qual é. Se não souber, mantenha o banco em execução, entre com `docker compose exec db psql -U diariodev -d diariodev`, digite `\password diariodev`, informe duas vezes o valor atual de `POSTGRES_PASSWORD` do `.env` e saia com `\q`. Depois execute `docker compose up -d`. Isso preserva os registros.
- Para ver o erro de inicialização, execute `docker compose logs --tail 50 db api`.

## API Web

| Método e rota | Acesso | Resultado |
|---|---|---|
| `GET /api/web/health` | Público | `200`, `{"status":"ok"}` |
| `POST /api/web/login` | Público | Recebe JSON `{"username":"...","password":"..."}`; cria a sessão ou retorna `401` |
| `GET /api/web/me` | Sessão | Retorna o usuário autenticado ou `401` |
| `POST /api/web/logout` | Sessão | Encerra a sessão ou retorna `401` |
| `POST /api/web/records` | Sessão | Cria um registro (`201`), ou retorna `400` com `errors` por campo / `401` |
| `PUT /api/web/records/{id}` | Sessão | Edita um registro (`200`), ou retorna `400` / `401` / `404` |
| `GET /api/web/records` | Sessão | Lista cinco registros por página, com ordenação; retorna `401` sem sessão |
| `GET /api/web/records/search` | Sessão | Busca com filtros combináveis e paginação; retorna `400` para filtros inválidos e `401` sem sessão |
| `DELETE /api/web/records/{id}` | Sessão | Exclui um registro (`204`), ou retorna `401` / `404` |
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

## Listagem e exclusão na Web (issue #3)

Ao entrar ou recarregar a página com uma sessão válida, a tabela busca os registros no banco e mostra **título, assunto, data do estudo e minutos estudados**. Cada página tem cinco itens. Os controles permitem ordenar por qualquer um desses campos em ordem crescente ou decrescente e navegar entre páginas. Em empates, o ID decrescente mantém uma ordem estável.

Selecione um registro pela primeira coluna e clique em **Excluir selecionado**. Após a confirmação, a página chama `DELETE /api/web/records/{id}` e atualiza a tabela. O formulário de cadastro/edição também atualiza a tabela após salvar. Se o último item de uma página for excluído, a página volta para a anterior.

`GET /api/web/records` aceita `page` (inteiro a partir de 1), `sort` (`study_date`, `title`, `topic` ou `minutes`) e `direction` (`asc` ou `desc`). Os padrões são `page=1`, `sort=study_date` e `direction=desc`. A resposta contém `items`, `page`, `page_size`, `total` e `total_pages`; parâmetros inválidos retornam `400`. O registro inexistente retorna `404` na exclusão. Listagem e exclusão exigem login e geram logs JSON correlacionados nas camadas API e banco.

## Busca avançada na Web (issue #4)

Após o login, use os filtros **Autor**, **Categoria (assunto)** e **período** (De/Até) acima da tabela. Clique em **Buscar** para atualizar os resultados sem recarregar a página. Os filtros podem ser combinados; **Limpar filtros** volta à listagem completa. A ordenação e a paginação de cinco itens continuam funcionando nos resultados filtrados.

`GET /api/web/records/search` aceita `author` (nome do usuário que criou o registro, sem diferenciar maiúsculas), `category` (trecho do campo `topic`, sem diferenciar maiúsculas), `date_from` e `date_to` (datas inclusivas em `AAAA-MM-DD`). Também aceita `page`, `sort` e `direction` com as mesmas regras da listagem. A resposta tem `items`, `page`, `page_size`, `total` e `total_pages`. Datas inválidas, período invertido, paginação ou ordenação inválida retornam `400`; sem sessão, retorna `401`.

O banco adiciona a coluna `author` aos registros existentes ao iniciar: registros antigos recebem o usuário inicial configurado naquele momento. Novos registros criados pela Web ou CLI recebem automaticamente o usuário autenticado, sem campo extra no formulário ou comando. A categoria usa o campo `topic` já existente. A busca tem consulta SQL própria, combina os filtros com `AND` e registra leituras tanto na API quanto no banco com o mesmo `request_id`.

## Rodar a CLI

O `docker compose up -d` inicia o contêiner `cli` junto com Web, API e banco. Ele fica pronto para receber comandos; você não precisa executar `docker compose run` antes. Na pasta do projeto:

1. Confira os comandos disponíveis e a conexão com a API:

   ```sh
   docker compose exec cli python cli.py --help
   docker compose exec cli python cli.py health
   ```

   O segundo comando deve responder `API da CLI saudável.`.

2. Gere um token com o usuário inicial:

   ```sh
   docker compose exec cli python cli.py token --username admin
   ```

   Troque `admin` se você mudou `INITIAL_USERNAME` no `.env`. Quando aparecer `Senha:`, digite **a senha escolhida ao gerar o hash**, não o hash. A CLI mostrará um token; copie-o inteiro.

3. No PowerShell, guarde o token só nesta sessão do terminal e confirme o login:

   ```powershell
   $env:DIARIODEV_TOKEN = (Read-Host 'Cole o token exibido pela CLI').Trim()
   docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py me
   ```

   O resultado esperado é `Usuário: admin` (ou o nome configurado). No Bash, use `export DIARIODEV_TOKEN='TOKEN_REAL'` e depois `docker compose exec -e DIARIODEV_TOKEN="$DIARIODEV_TOKEN" cli python cli.py me`.

O token vence após uma hora; execute o passo 2 novamente para renová-lo. Não publique o token. A CLI oferece `health`, `token`, `me`, `create`, `edit`, `list` e `delete`. Uma senha incorreta retorna `HTTP 401: Invalid credentials`; um token ausente ou inválido retorna `HTTP 401: Unauthorized`.

Para automações, `docker compose exec -T cli python cli.py token --username admin --password-stdin` lê a senha pela entrada padrão sem mostrá-la nos argumentos do processo.

| Método e rota | Acesso | Resultado |
|---|---|---|
| `GET /api/cli/health` | Público | `200`, `{"status":"ok"}` |
| `POST /api/cli/token` | Público | Recebe usuário e senha em JSON; retorna `token`, `token_type` e `expires_in`, ou `401` |
| `GET /api/cli/me` | Bearer token | Retorna o usuário autenticado ou `401` |

Os endpoints CLI são separados dos endpoints Web. O token é assinado com `SESSION_SECRET` e não é registrado nos logs. Os comandos `create` e `edit` usam essa autenticação.


## Criar e editar registros pela CLI (issue #8)

Com um token válido em `$env:DIARIODEV_TOKEN` no PowerShell (veja a seção anterior), use `create` com os mesmos cinco campos do formulário Web. O comando mostra o ID gerado:

```powershell
docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py create --title "Git" --topic "Worktree" --summary "Estudei branches isoladas" --study-date 2026-11-15 --minutes 30
```

Use o ID retornado para editar o registro. `edit` recebe o registro inteiro, portanto informe novamente os cinco campos, inclusive os que não mudaram:

```powershell
docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py edit 1 --title "Git" --topic "Worktree" --summary "Pratiquei git worktree" --study-date 2026-11-15 --minutes 45
```

No Bash, use `-e DIARIODEV_TOKEN="$DIARIODEV_TOKEN"` no lugar de `-e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN`. Para ver as opções, execute `docker compose exec cli python cli.py create --help` ou `docker compose exec cli python cli.py edit --help`. `title`, `topic` e `summary` não podem ficar vazios e têm limites de 120, 60 e 1000 caracteres; `study_date` deve ser uma data válida `AAAA-MM-DD`; `minutes` deve ser um inteiro entre 0 e 1440. A API aplica a **mesma validação da Web**, remove espaços nas pontas dos textos e devolve `400` com erros por campo. A CLI exibe esses erros no terminal e sai com código 1. ID inexistente retorna `404`; sem token válido, `401`.

| Método e rota | Acesso | Resultado |
|---|---|---|
| `POST /api/cli/records` | Bearer token | Cria no PostgreSQL e retorna o registro com ID (`201`) |
| `PUT /api/cli/records/{id}` | Bearer token | Atualiza o mesmo registro e retorna seus dados (`200`); ID inexistente retorna `404` |

A CLI chama apenas esses endpoints REST. A API usa `db.py` para gravar na mesma tabela `records` utilizada pela Web. Os registros criados ou editados pela CLI aparecem na listagem Web ao abrir ou atualizar a página. Para conferir os logs correlacionados de API e banco, execute `docker compose logs -f api`: eventos `create`/`update` na camada `api` e `insert`/`update` na camada `db` compartilham `request_id` e usam `client: "cli"`.


## Listar e excluir registros pela CLI (issue #9)

Com um token válido em `$env:DIARIODEV_TOKEN` (veja "Rodar a CLI"), liste os registros com paginação e ordenação:

```powershell
docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py list
docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py list --page 2 --page-size 3 --sort title --direction asc
```

| Opção | Valores | Padrão |
|---|---|---|
| `--page` | inteiro a partir de 1 | `1` |
| `--page-size` | de 1 a 50 | `5` |
| `--sort` | `study_date`, `title`, `topic` ou `minutes` | `study_date` |
| `--direction` | `asc` ou `desc` | `desc` |

Cada linha mostra `#id | data | título | assunto | minutos`, e a última informa a página atual, o total de páginas e o total de registros. Em empates, o ID decrescente mantém a ordem estável, como na Web.

Para excluir, informe o identificador mostrado na listagem:

```powershell
docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py delete 3
```

A CLI responde `Registro #3 excluído.`. Um ID inexistente retorna `HTTP 404: Record not found` e parâmetros inválidos retornam `HTTP 400`; sem token válido, `HTTP 401`. No Bash, use `-e DIARIODEV_TOKEN="$DIARIODEV_TOKEN"`. Como a CLI e a Web usam a mesma tabela `records`, o que for listado ou excluído pela CLI aparece (ou some) na tabela Web ao recarregar a página.

| Método e rota | Acesso | Resultado |
|---|---|---|
| `GET /api/cli/records` | Bearer token | Recebe `page`, `page_size`, `sort` e `direction`; retorna `items`, `page`, `page_size`, `total` e `total_pages` (`200`), ou `400` / `401` |
| `DELETE /api/cli/records/{id}` | Bearer token | Exclui o registro e retorna `{"id": id, "deleted": true}` (`200`); `404` se não existir, `401` sem token |

A CLI chama apenas esses endpoints REST, que usam as consultas próprias `list_records_cli` e `delete_record_cli` de `db.py`. Os logs saem com `client: "cli"`, operações `list` e `delete`, e a mesma `request_id` nas camadas `api` e `db`: consulte com `docker compose logs -f api`.

## Status do registro na Web (issue #13)

Todo registro tem um status `active` (padrão) ou `inactive`, salvo na coluna `records.status` (adicionada automaticamente na inicialização da API). Ao editar um registro, a página mostra o status atual e o botão **Ativar/Desativar**, que chama `PATCH /api/web/records/{id}/status` e persiste a mudança no PostgreSQL. As respostas de registros incluem o campo `status`.

```sh
curl -b cookies.txt -X PATCH -H 'Content-Type: application/json' -d '{"status":"inactive"}' http://localhost:8080/api/web/records/1/status
```

Logs: a API registra `status` e `db.py` registra `update_status`, com o mesmo `request_id`.

## Status do registro pela CLI (issue #14)

Com um token válido em `$env:DIARIODEV_TOKEN` (veja "Rodar a CLI"), ative ou desative um registro informando o identificador mostrado em `list` e o novo status (`active` ou `inactive`):

```powershell
docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py status 3 inactive
docker compose exec -e DIARIODEV_TOKEN=$env:DIARIODEV_TOKEN cli python cli.py status 3 active
```

A CLI responde `Registro #3: inativo.` ou `Registro #3: ativo.`. Um ID inexistente retorna `HTTP 404: Record not found`; sem token válido, `HTTP 401`; um status diferente de `active` e `inactive` é recusado pela própria CLI (ou com `400` pela API). No Bash, use `-e DIARIODEV_TOKEN="$DIARIODEV_TOKEN"`. O status fica salvo em `records.status`, a mesma coluna da Web: ao recarregar a página e abrir o registro em **Editar**, ele aparece como **Ativo** ou **Inativo**.

| Método e rota | Acesso | Resultado |
|---|---|---|
| `PATCH /api/cli/records/{id}/status` | Bearer token | Recebe `{"status":"active"\|"inactive"}`; retorna o registro (`200`), `400` / `401` / `404` |

A CLI chama apenas esse endpoint REST, que usa a consulta própria `update_status_cli` de `db.py` (separada da consulta Web). Os logs saem com `client: "cli"`, operação `status` na camada `api` e `update_status` na camada `db`, com a mesma `request_id`: consulte com `docker compose logs -f api`.


## Exportação CSV pela Web (issue #5)

Após entrar, vá até **Seus registros**, aplique os filtros com **Buscar** e clique
em **Exportar CSV**. O navegador baixa `registros.csv` com todos os resultados da
busca, inclusive os que estão em outras páginas. A seleção de uma linha e a página
atual não limitam o arquivo. **Limpar filtros** volta a exportar todos os registros,
tanto ativos quanto inativos. A exportação usa os últimos filtros aplicados com
**Buscar**; editar os campos sem buscar ainda não altera os resultados exportados.

O endpoint protegido `GET /api/web/records/export` usa os mesmos filtros da
busca da issue #4, combinados com **E**:

| Parâmetro | Significado |
|---|---|
| `author` | Nome completo do usuário autor, sem diferenciar maiúsculas/minúsculas |
| `category` | Trecho literal do assunto (`topic`), sem diferenciar maiúsculas/minúsculas |
| `date_from` | Data inicial inclusiva do estudo, `AAAA-MM-DD` |
| `date_to` | Data final inclusiva do estudo, `AAAA-MM-DD` |
| `sort` | `study_date` (padrão), `title`, `topic` ou `minutes` |
| `direction` | `desc` (padrão) ou `asc` |

As datas também podem ser usadas separadamente. `%` e `_` não são curingas.
A ordenação da listagem é preservada. `page`, `page_size`, `limit` e `offset` são
aceitos e ignorados; a consulta SQL própria de exportação em `db.py` nunca aplica
`LIMIT`/`OFFSET`. Ela não reutiliza a consulta paginada da busca.

Sem sessão válida, retorna `401`. Datas inválidas, intervalo invertido, ordenação
inválida ou parâmetros desconhecidos retornam `400` com `errors`. Falha no banco
retorna `503` e a página exibe uma mensagem sem baixar um arquivo de erro.

O sucesso retorna `200`, `Content-Type: text/csv; charset=utf-8` e
`Content-Disposition: attachment; filename="registros.csv"`. O CSV usa vírgula,
cabeçalho `id,title,topic,summary,study_date,minutes,status`, datas ISO e UTF-8 com
BOM para preservar acentos em planilhas. Aspas, vírgulas e quebras de linha são
escapadas pelo formato CSV. Sem resultados, retorna apenas o cabeçalho.
API e banco registram `export` com o mesmo `request_id`; consulte com
`docker compose logs -f api`.

Para conferir na Web, crie mais de cinco registros correspondentes aos mesmos
filtros, aplique a busca, vá para a segunda página e exporte: o arquivo deve conter
todos os resultados. Limpe os filtros e exporte todos os registros. Confira também
uma busca sem resultados e uma tentativa sem sessão.

Além dos testes unitários abaixo, `tests/test_export_integration.py` verifica a
rota e o SQL com PostgreSQL real, criando e removendo somente um schema temporário
próprio, sem alterar os registros da aplicação. Com o banco em execução, rode:

```sh
docker compose run --rm --no-deps --build api python -c "import os, subprocess; os.environ['TEST_DATABASE_URL'] = os.environ['DATABASE_URL']; subprocess.run(['pytest', '-q', 'tests/test_export_integration.py'], check=True)"
```

Os testes de integração criam registros temporários, comparam o CSV com todas as
páginas da busca e verificam filtros combinados, datas, caracteres especiais e a
criação pela CLI após a migração de autor. Sem `TEST_DATABASE_URL`, são pulados
na execução unitária. A criação pela CLI grava o autor do token conforme a
implementação da #4, mantendo a compatibilidade com a coluna obrigatória.

Esta entrega corresponde à **PR 2 do ciclo 3 (issue #5)** e usa a busca avançada
da **issue #4 / PR #23**, já integrada ao `main`. A PR de exportação contém apenas
as alterações da #5 e exige a aprovação de todos os colegas antes da integração.

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

A suíte deve passar com **100% de cobertura**. Para consultar os logs JSON da API e do acesso ao banco, use `docker compose logs -f api`; pressione `Ctrl+C` para parar de acompanhar os logs.

Para encerrar os serviços sem apagar os dados do volume PostgreSQL:

```sh
docker compose down
```
