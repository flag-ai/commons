# FLAG Commons

Shared Python library for the FLAG (Foundation for Local AI Governance)
platform. It provides the contracts every FLAG component shares: version
info, structured logging, secrets, configuration, PostgreSQL access, health
checks, the BONNIE agent client, and BONNIE provisioning.

> The Go implementation is preserved at tag `go-final-v0.2.1` (identical to
> `v0.2.1`). Go module consumers must keep pinning `v0.2.1`; the `v0.3.0` tag
> and later contain no `go.mod`, so Go tooling sees an empty module there.
> BONNIE, which stays in Go, vendored the packages it needs.

## Packages

| Package | Purpose |
|---|---|
| `flag_commons.version` | `info(dist)` → `"X (commit: Y, built: Z)"` from `importlib.metadata` + `FLAG_BUILD_*` |
| `flag_commons.logging` | stdlib root logger with slog-compatible text/JSON output, `bind()` context fields |
| `flag_commons.secrets` | `EnvProvider`, `OpenBaoProvider` (KV v2), `ChainProvider`, `provider_from_env()` |
| `flag_commons.config` | `BaseConfig` (pydantic), `load_base()`, `bind_address()` |
| `flag_commons.health` | `Registry`, `Checker`, `DatabaseChecker`, `HttpChecker`, FastAPI `/health` + `/ready` |
| `flag_commons.database` | SQLAlchemy 2 + psycopg 3 engines, startup ping, Alembic under an advisory lock |
| `flag_commons.bonnie` | `BonnieClient`, tolerant SSE parser, wire models, `AgentRegistry` |
| `flag_commons.install` | install-script rendering, agent self-registration, FastAPI router |

See [docs/usage.md](docs/usage.md) for the component bootstrap and
[CHANGELOG.md](CHANGELOG.md) for the differences from the Go library.

## Installation

```toml
[tool.poetry.dependencies]
flag-commons = {git = "https://github.com/flag-ai/commons", tag = "v0.3.0", extras = ["postgres", "fastapi"]}
```

Python 3.10 to 3.13.

## Extras

| Extra | Adds | Needed for |
|---|---|---|
| `postgres` | SQLAlchemy 2 (asyncio), psycopg 3, Alembic | `flag_commons.database`, `DatabaseChecker` |
| `fastapi` | FastAPI | `health.fastapi.health_router`, `install.fastapi.install_router` |

## Development

```bash
poetry install --with dev --extras all
poetry run pytest tests/unit
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/db poetry run pytest tests/integration
poetry run ruff check src tests && poetry run ruff format --check src tests
poetry run mypy
poetry run bandit -c pyproject.toml -r src
```

CI runs `lint`, `test (ubuntu-latest, 3.10…3.13)`, `integration` (Postgres
17 service) and `security` (bandit + pip-audit) on pushes and pull requests
to `main` and `rewrite/python`.

## License

Apache 2.0
