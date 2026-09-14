# FLAG Commons

Shared Python library for the FLAG (Foundation for Local AI Governance) platform.
It provides the foundational contracts used by FLAG components. On this branch
the `version`, `logging`, `secrets` and `config` packages are ported; `health`,
`database`, `bonnie` and `install` follow in later PRs of the rewrite.

> **Rewrite in progress.** This tree replaces the Go library, which is preserved
> at tag `go-final-v0.2.1` (identical to `v0.2.1`). Go module consumers must keep
> pinning `v0.2.1`; the `v0.3.0` tag and later contain no `go.mod`.

## Installation

```toml
[tool.poetry.dependencies]
flag-commons = {git = "https://github.com/flag-ai/commons", tag = "v0.3.0"}
```

## Development

```bash
poetry install --with dev --extras all
poetry run pytest
poetry run ruff check src tests && poetry run ruff format --check src tests
poetry run mypy
```

## License

Apache 2.0
