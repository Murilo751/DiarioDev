## Descrição e issue

Closes #

## Arquivos alterados

Liste os arquivos de produção e justifique cada arquivo auxiliar (testes, dependências, infraestrutura ou configuração).

## API, autenticação e logs

Descreva os endpoints, a proteção de acesso e os eventos de log da API e do banco.

## Verificação

- [ ] `docker compose up --build -d`
- [ ] `docker compose run --rm --no-deps tests` — 100% de cobertura de linhas em `api.py` e `db.py`
- [ ] Health 200, login válido e 401 sem sessão conferidos
- [ ] Aprovação de todos os colegas antes do merge
