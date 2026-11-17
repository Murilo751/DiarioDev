# DiarioDev

Diário de estudos com interface Web, CLI, API Flask e PostgreSQL. Web e CLI trabalham com os mesmos registros; todas as partes rodam pelo Docker Compose.

## Neste guia

- [Início rápido](#início-rápido)
- [Usar a Web](#usar-a-web)
- [Usar a CLI](#usar-a-cli)
- [API e dados](#api-e-dados)
- [Logs](#logs)
- [Testes e cobertura](#testes-e-cobertura)
- [Problemas comuns](#problemas-comuns)

## Início rápido

Você precisa apenas de **Docker com Docker Compose**, navegador e terminal. Execute os comandos na pasta que contém `compose.yaml`. No Windows, inicie o Docker Desktop antes de continuar; `docker info` deve responder normalmente.

### 1. Configure o usuário e o banco

Crie o arquivo local `.env` a partir do exemplo. Se ele já existe, mantenha-o: a senha pode estar vinculada a um volume PostgreSQL anterior.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose build api
```

No Bash, use `test -f .env || cp .env.example .env` no primeiro comando. Gere o **hash** da senha inicial; o contêiner pedirá a senha sem exibi-la:

```sh
docker compose run --rm --no-deps api python -c "from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass('Senha inicial: ')))"
```

Edite `.env`: escolha `INITIAL_USERNAME` (padrão: `admin`) e cole o resultado em `INITIAL_PASSWORD_HASH` **entre aspas simples**, por exemplo `INITIAL_PASSWORD_HASH='scrypt:...'`. As aspas preservam os caracteres `$` do hash.

Gere **dois segredos diferentes** com o comando abaixo, executado duas vezes. Use um em `SESSION_SECRET` e outro em `POSTGRES_PASSWORD`:

```sh
docker compose run --rm --no-deps api python -c "import secrets; print(secrets.token_hex(32))"
```

Guarde a senha que você digitou, não o hash. Nunca publique `.env`, senhas ou tokens; `.env` é ignorado pelo Git.

### 2. Inicie e entre

```sh
docker compose up --build -d
docker compose ps
docker compose exec web wget -qO- http://localhost/api/web/health
```

`web`, `api`, `db` e `cli` devem estar em execução; `api` e `db` devem ficar `healthy`. O healthcheck deve retornar `{"status":"ok"}`. Abra [http://localhost:8080](http://localhost:8080) e entre com `INITIAL_USERNAME` e a **senha escolhida**, não o hash.

Para iniciar novamente, use `docker compose up -d`. Para parar sem apagar os dados, use `docker compose down`. O volume `postgres_data` preserva os registros. Ao mudar o usuário ou o hash em `.env`, reinicie a API com `docker compose up -d --force-recreate api`.

## Usar a Web

Depois do login, a aba **Estudos** mostra a tabela; **Dashboard** mostra os gráficos. A sessão usa cookie `HttpOnly` e `SameSite=Lax`. O Nginx serve `index.html` e encaminha `/api` à API na mesma origem.

### #1 — Estrutura e login

Entre na página com o usuário inicial. **Sair** encerra a sessão. Sem sessão válida, as rotas funcionais retornam `401`.

### #2 — Cadastro e edição

Clique em **Adicionar estudo** para abrir o formulário. Para editar, clique na linha e depois em **Editar estudo**, ou use o ícone de edição.

### #3 — Listagem e exclusão

A tabela mostra título, assunto, data e minutos, com **cinco itens por página**. Use as setas para navegar e o ícone de exclusão para apagar após confirmação.

### #4 — Busca avançada

Abra **Filtros**, combine autor, assunto e período e clique em **Aplicar**. **Limpar** volta à lista completa; ordenação e paginação continuam disponíveis.

### #5 — Exportação CSV

Clique em **Exportar CSV**. O arquivo inclui **todos** os registros dos filtros aplicados, inclusive os de outras páginas; sem filtros, inclui todos.

### #6 — Dashboard

A aba **Dashboard** mostra três gráficos com dados reais: registros por assunto, autor e mês. Os valores são carregados ao abrir/recarregar a aba.

### #13 — Status

No formulário de edição, use **Ativar/Desativar**. O estado `active` ou `inactive` fica salvo no banco.

### #15 — Duplicação

Use o ícone de duplicar na linha. A cópia recebe outro ID e o usuário logado como autor; o original permanece intacto.

A linha também abre uma visualização do estudo com resumo, data, duração e status. As ações da tabela ficam na última coluna.

### Campos e filtros

| Campo do estudo | Regra |
|---|---|
| Título (`title`) | Obrigatório, até 120 caracteres |
| Assunto (`topic`) | Obrigatório, até 60 caracteres |
| Resumo (`summary`) | Obrigatório, até 1000 caracteres |
| Data do estudo (`study_date`) | Obrigatória, data válida `AAAA-MM-DD` |
| Minutos (`minutes`) | Obrigatório, inteiro de 0 a 1440 |

A página e a API validam os campos; erros aparecem junto ao formulário. O autor é o usuário autenticado e a categoria dos filtros é o `topic`. Registros anteriores à coluna `author` receberam o usuário inicial quando essa coluna foi criada.

Os filtros de busca podem ser combinados: `author` corresponde ao nome completo sem diferenciar maiúsculas; `category` procura um trecho literal do assunto sem diferenciar maiúsculas; `date_from` e `date_to` são datas inclusivas. Datas podem ser usadas separadamente; um período invertido retorna `400`. A ordenação aceita `study_date`, `title`, `topic` ou `minutes`, com direção `asc` ou `desc`. Empates usam o ID decrescente.

O CSV usa UTF-8 com BOM, vírgulas e o cabeçalho `id,title,topic,summary,study_date,minutes,status`. Preserva os filtros e a ordenação **já aplicados**; editar os campos sem clicar em **Aplicar** ainda não muda o arquivo. Inclui registros ativos e inativos. Sem resultados, contém apenas o cabeçalho.

O Dashboard conta até dez assuntos e dez autores (maiores totais, desempate alfabético) e os 12 meses mais recentes com registros (exibidos em ordem cronológica). Sem dados, os gráficos mostram uma mensagem de vazio.

## Usar a CLI

### Menu interativo

Abra o menu no terminal:

```sh
docker compose up --build -d
docker compose exec cli python cli.py
```

Também pode usar `docker compose exec cli python cli.py menu`. Entre com o
`INITIAL_USERNAME` e a senha escolhida na configuração. A senha não aparece na
tela; o token fica somente na memória da sessão, sem precisar copiá-lo. Credenciais
incorretas mostram uma mensagem de login inválido; token expirado pede novo login.

A tela **Estudos** mostra título, assunto, data, minutos e status, com cinco
registros por página. Digite o número da opção e pressione Enter:

| Opção | Ação |
|---|---|
| 1 | Adicionar estudo com perguntas para os cinco campos |
| 2 | Abrir estudo da página atual pelo ID; editar, mudar status, duplicar ou excluir |
| 3 | Aplicar ou limpar filtros por autor, assunto e período |
| 4 | Ordenar por data, título, assunto ou minutos |
| 5 | Exportar todos os resultados filtrados em CSV |
| 6 | Dashboard com os mesmos três indicadores da Web |
| 7 / 8 | Página anterior / próxima |
| 9 | Sair da conta |
| 0 | Encerrar o menu |

Na edição, Enter mantém o valor atual. Digite `:voltar` em um formulário para
cancelar; no campo de usuário, ele encerra o menu. Ctrl+C também encerra a sessão.
A exclusão exige confirmação. Cadastro, edição, status, duplicação e exclusão
aparecem na Web ao atualizar a página.

O CSV respeita os filtros e a ordenação aplicados, incluindo outras páginas. O
arquivo fica no contêiner; para copiar o nome padrão ao computador:

```sh
docker compose cp cli:/app/registros.csv ./registros.csv
```

O menu usa exclusivamente os endpoints REST da CLI, sem acesso direto ao banco,
e mantém os logs correlacionados da API e do banco. Os subcomandos abaixo continuam
disponíveis para automação e uso direto.


O `docker compose up -d` também inicia o contêiner `cli`. Confira a ajuda e a conexão com a API:

```sh
docker compose exec cli python cli.py --help
docker compose exec cli python cli.py health
```

O healthcheck da CLI responde `API da CLI saudável.`.

### #7 — Obter e usar o token

```sh
docker compose exec cli python cli.py token --username admin
```

Use o `INITIAL_USERNAME` configurado se for diferente de `admin`. Digite a **senha escolhida** quando a CLI pedir; ela imprimirá um token válido por uma hora. Guarde-o somente na sessão do terminal:

```powershell
$env:DIARIODEV_TOKEN = (Read-Host 'Cole o token').Trim()
docker compose exec -e DIARIODEV_TOKEN cli python cli.py me
```

No Bash: `export DIARIODEV_TOKEN='TOKEN'` e depois o mesmo comando `docker compose exec -e DIARIODEV_TOKEN cli python cli.py me`. O Compose repassa a variável do host ao contêiner. O resultado esperado é `Usuário: admin` (ou seu usuário). Renove o token executando `token` novamente. Para automação, `token --username admin --password-stdin` lê a senha da entrada padrão sem colocá-la nos argumentos do processo. Não publique o token.

Nos exemplos abaixo, `-e DIARIODEV_TOKEN` pressupõe que você já definiu essa variável no terminal.

### Comandos de registros

Use um registro de exemplo para preparar dados e conferir a Web:

```powershell
docker compose exec -e DIARIODEV_TOKEN cli python cli.py create --title "Git" --topic "Worktree" --summary "Estudei branches isoladas" --study-date 2026-11-15 --minutes 30
docker compose exec -e DIARIODEV_TOKEN cli python cli.py list
```

### #8 — Criar e editar

`create` usa os cinco campos obrigatórios. `edit ID` recebe **novamente todos os cinco campos** e atualiza o registro. Os mesmos dados aparecem na Web.

### #9 — Listar e excluir

`list` mostra `#id | data | título | assunto | minutos` e a paginação; `delete ID` exclui pelo identificador. A Web reflete a alteração ao recarregar.

### #10 — Busca avançada

`search` combina `--author`, `--category`, `--date-from` e `--date-to`. Com os mesmos parâmetros, os resultados equivalem à busca Web.

### #11 — Exportação CSV

`export` grava **todos** os resultados filtrados, sem limitar à página atual, em `/app/registros.csv` dentro do contêiner.

### #12 — Indicadores

`dashboard` mostra em texto as contagens por categoria, autor e mês, com os mesmos valores do Dashboard Web.

### #14 — Status

`status ID active` ou `status ID inactive` salva o novo estado; ele aparece na Web.

### #16 — Duplicação

`duplicate ID` cria uma cópia com novo ID e autor do token, preservando todos os dados do original.

Exemplos de cada operação:

```powershell
docker compose exec -e DIARIODEV_TOKEN cli python cli.py edit 1 --title "Git" --topic "Worktree" --summary "Pratiquei git worktree" --study-date 2026-11-15 --minutes 45
docker compose exec -e DIARIODEV_TOKEN cli python cli.py list --page 2 --page-size 3 --sort title --direction asc
docker compose exec -e DIARIODEV_TOKEN cli python cli.py search --author admin --category Git --date-from 2026-11-01 --date-to 2026-11-30
docker compose exec -e DIARIODEV_TOKEN cli python cli.py export --category Git --output filtrados.csv
docker compose cp cli:/app/filtrados.csv ./filtrados.csv
docker compose exec -e DIARIODEV_TOKEN cli python cli.py dashboard
docker compose exec -e DIARIODEV_TOKEN cli python cli.py status 1 inactive
docker compose exec -e DIARIODEV_TOKEN cli python cli.py duplicate 1
docker compose exec -e DIARIODEV_TOKEN cli python cli.py delete 1
```

`list` e `search` aceitam `--page` (padrão 1), `--page-size` (1 a 50; padrão 5), `--sort` (`study_date`, `title`, `topic` ou `minutes`) e `--direction` (`asc` ou `desc`). `search` e `export` aceitam os quatro filtros; `export` aceita também ordenação e `--output` (padrão `registros.csv`). Use `docker compose exec cli python cli.py COMANDO --help` para ver cada opção. A CLI chama somente endpoints REST próprios, sem acessar o banco diretamente.

Parâmetros inválidos retornam `400`; ID inexistente, `404`; credenciais ou token inválidos, `401`; falha no banco, `503`. O comando sai com código 1 e imprime o erro. A senha inicial é armazenada somente como hash no banco.

## API e dados

A API Flask e o PostgreSQL são compartilhados pela Web e CLI. As rotas funcionais são separadas por cliente, têm autenticação própria e consultas SQL próprias em `db.py`. A tabela `users` guarda o usuário inicial e o hash; `records` guarda os cinco campos do estudo, autor e status. Os dados persistem no volume `postgres_data`.

| Operação | Rota Web (sessão) | Rota CLI (Bearer token) |
|---|---|---|
| Healthcheck público | `GET /api/web/health` | `GET /api/cli/health` |
| Autenticação | `POST /api/web/login`, `GET /api/web/me`, `POST /api/web/logout` | `POST /api/cli/token`, `GET /api/cli/me` |
| Listar | `GET /api/web/records` | `GET /api/cli/records` |
| Criar | `POST /api/web/records` | `POST /api/cli/records` |
| Editar | `PUT /api/web/records/{id}` | `PUT /api/cli/records/{id}` |
| Excluir | `DELETE /api/web/records/{id}` | `DELETE /api/cli/records/{id}` |
| Buscar | `GET /api/web/records/search` | `GET /api/cli/records/search` |
| Exportar CSV | `GET /api/web/records/export` | `GET /api/cli/records/export` |
| Indicadores | `GET /api/web/dashboard` | `GET /api/cli/dashboard` |
| Alterar status | `PATCH /api/web/records/{id}/status` | `PATCH /api/cli/records/{id}/status` |
| Duplicar | `POST /api/web/records/{id}/duplicate` | `POST /api/cli/records/{id}/duplicate` |

`{id}` é o identificador do registro. O login Web recebe `{"username":"...","password":"..."}` e cria uma sessão; o token CLI recebe as mesmas credenciais e retorna `token`, `token_type` e `expires_in`. Todas as operações funcionais exigem credencial válida e respondem **HTTP 401** em caso contrário. Healthchecks são públicos. As respostas de listagem e busca contêm `items`, `page`, `page_size`, `total` e `total_pages`; a exportação retorna `text/csv`; os indicadores retornam `by_category`, `by_author` e `by_month`, cada um com objetos `{"label":"...","total":N}`.

## Logs

Acompanhe os eventos JSON da API e do acesso ao banco (inclusive leituras):

```sh
docker compose logs -f api
```

Cada linha contém `timestamp` (UTC ISO 8601), `level` (`INFO`/`WARN`/`ERROR`), `layer` (`api`/`db`), `client` (`web`/`cli`), `operation`, `status` (`success`/`error`), `request_id` e `message`. Uma operação que acessa o banco emite eventos nas duas camadas com o **mesmo `request_id`**. Sucessos e falhas de autenticação são registrados sem senhas, hashes, tokens, payloads completos ou SQL.

Para conferir a correlação, crie um estudo na Web, execute `list` na CLI e procure no log os pares de eventos com o mesmo `request_id` em cada requisição.

## Testes e cobertura

Os testes unitários e a medição de cobertura rodam **somente pelo Compose**:

```sh
docker compose run --rm --no-deps --build tests
```

A suíte exige **100% de cobertura de linhas de `api.py`, `cli.py` e `db.py`**. `index.html`, testes, infraestrutura e configuração não entram nessa métrica.

Com `db` em execução, há também testes de integração que usam schemas temporários próprios, sem alterar os registros da aplicação:

```sh
docker compose run --rm --no-deps --build api python -c "import os, subprocess; os.environ['TEST_DATABASE_URL'] = os.environ['DATABASE_URL']; subprocess.run(['pytest', '-q', 'tests/test_export_integration.py'], check=True)"
docker compose run --rm --no-deps --build api python -c "import os, subprocess; os.environ['TEST_DATABASE_URL'] = os.environ['DATABASE_URL']; subprocess.run(['pytest', '-q', 'tests/test_duplicate_integration.py', 'tests/test_cli_menu_integration.py'], check=True)"
```

O teste `tests/test_cli_menu_integration.py` percorre login, cadastro, edição com valores preservados, status, duplicação, confirmação de exclusão, filtros, paginação, CSV e dashboard pelo menu, via HTTP e PostgreSQL real. Compara os dados com a API Web e verifica logs correlacionados. Cada teste usa um schema temporário próprio.

Esses testes são ignorados na suíte unitária quando `TEST_DATABASE_URL` não está definida. Para verificar manualmente: crie mais de cinco estudos, use filtros combinados na Web e na CLI, compare os resultados, exporte o CSV e confira que contém todas as páginas; duplique um registro e confira os IDs na Web.

## Problemas comuns

- `docker info` falha: inicie o Docker Desktop e aguarde o mecanismo de contêineres.
- A API não inicia: consulte `docker compose logs --tail 50 db api`.
- `password authentication failed for user "diariodev"`: o volume antigo foi criado com outro `POSTGRES_PASSWORD`. Reuse a senha antiga; se não a souber, altere a senha do usuário no PostgreSQL em execução com `docker compose exec db psql -U diariodev -d diariodev`, `\password diariodev` e `\q`, depois reinicie a API. Isso preserva os dados.
- `HTTP 401`: confira o usuário e a senha inicial; para a CLI, gere outro token após uma hora e defina `DIARIODEV_TOKEN` no terminal.
- `.env` ou o token não devem ser enviados ao Git. Para parar sem apagar os registros, use `docker compose down`.
