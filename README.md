# FLAG Commons

Shared Python library for the FLAG (Foundation for Local AI Governance) platform.
It provides the foundational contracts used by FLAG components. On this branch
the `version`, `logging`, `secrets`, `config`, `health` and `database` packages
are ported; `bonnie` and `install` follow in later PRs of the rewrite.

> **Rewrite in progress.** This tree replaces the Go library, which is preserved
> at tag `go-final-v0.2.1` (identical to `v0.2.1`). Go module consumers must keep
> pinning `v0.2.1`; the `v0.3.0` tag and later contain no `go.mod`.

## Installation

```toml
[tool.poetry.dependencies]
flag-commons = {git = "https://github.com/flag-ai/commons", tag = "v0.3.0"}
```

## Extras

| Extra | Adds | Needed for |
|---|---|---|
| `postgres` | SQLAlchemy 2 (asyncio), psycopg 3, Alembic | `flag_commons.database`, `DatabaseChecker` |
| `fastapi` | FastAPI | `flag_commons.health.fastapi.health_router` |

## Development

```bash
poetry install --with dev --extras all
poetry run pytest tests/unit
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/db poetry run pytest tests/integration
poetry run ruff check src tests && poetry run ruff format --check src tests
poetry run mypy
```

## License

Apache 2.0
