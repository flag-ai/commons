# Using flag-commons in a FLAG component

This is the bootstrap every FLAG Python service follows. KARR is the first
adopter; KITT and DEVON adopt it in a later phase.

## Install

```toml
[tool.poetry.dependencies]
flag-commons = {git = "https://github.com/flag-ai/commons", tag = "v0.3.0", extras = ["postgres", "fastapi"]}
```

The Git dependency needs `git` in the Docker builder stage.

## Bootstrap order

1. **Secrets.** `provider_from_env()` returns `ChainProvider([Env, OpenBao])`
   when `OPENBAO_ADDR` and `OPENBAO_TOKEN` are set, otherwise `EnvProvider`.
   Environment variables always win; OpenBao fills the gaps. OpenBao keys use
   the `path#field` form (`infra/karr#postgres_password`).
2. **Config.** Subclass `BaseConfig` and read your own keys through the same
   provider.
3. **Logging.** `cfg.setup_logging()` configures the stdlib root logger.
4. **Database.** `await connect(url)` builds the engine and pings it with
   backoff; `run_migrations(script_dir, url)` applies the packaged Alembic
   scripts under an advisory lock.
5. **Health.** Register checkers, mount `health_router()`.
6. **Version.** Bake `FLAG_BUILD_COMMIT` and `FLAG_BUILD_DATE` into the image.

```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import SecretStr

from flag_commons.bonnie import AgentRegistry, BonnieAgentsChecker
from flag_commons.config import BaseConfig
from flag_commons.database import DatabaseChecker, connect, run_migrations_async
from flag_commons.health import Registry
from flag_commons.health.fastapi import health_router
from flag_commons.secrets import SecretsProvider, provider_from_env


class KarrConfig(BaseConfig):
    admin_token: SecretStr

    @classmethod
    def load(cls, provider: SecretsProvider) -> "KarrConfig":
        return cls(
            **cls.base_fields("karr", provider),
            admin_token=SecretStr(provider.get("KARR_ADMIN_TOKEN")),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = provider_from_env()
    cfg = KarrConfig.load(provider)
    cfg.setup_logging(dist_name="karr")

    url = cfg.database_url.get_secret_value()
    engine = await connect(url)
    await run_migrations_async(Path(__file__).parent / "db" / "migrations", url)

    agents = AgentRegistry(store=MyStore(engine))
    await agents.start()

    health = Registry(dist_name="karr")
    health.register(DatabaseChecker(engine))
    health.register(BonnieAgentsChecker(agents), critical=False)
    app.include_router(health_router(health))

    app.state.engine, app.state.agents = engine, agents
    try:
        yield
    finally:
        await agents.stop()
        await engine.dispose()


app = FastAPI(lifespan=lifespan)
```

Run it with `uvicorn.run(app, host=host, port=port, log_config=uvicorn_log_config("karr"))`
where `host, port = cfg.bind_address()`.

## The health contract

| Route | Meaning | Body |
|---|---|---|
| `GET /health` | liveness, always 200 | `{"status": "ok", "version": "<X (commit: Y, built: Z)>"}` |
| `GET /ready` | readiness, 503 when unhealthy | `{"healthy": bool, "version": str, "checks": [{"name", "healthy", "error"?, "latency_ms", "critical"?}]}` |

`critical` appears only when `false`; a non-critical failure is reported
without flipping `healthy`. Pass `redact_errors=True` when `/ready` is
reachable by untrusted callers.

## Talking to BONNIE

```python
from flag_commons.bonnie import BonnieClient, CreateContainerRequest

async with BonnieClient("http://gpu-01:7777", token) as bonnie:
    info = await bonnie.system_info()
    cid = await bonnie.create_container(CreateContainerRequest(name="env-1", image="vllm", gpu=True))
    await bonnie.start_container(cid)
    async for line in bonnie.stream_container_logs(cid):
        print(line)
```

Idempotent calls are retried on network errors and 429/502/503/504;
creates, start/stop/restart, exec and benchmark runs are not. Errors are
`BonnieError` subclasses: `BonnieUnauthorized`, `BonnieNotFound`,
`BonnieBadRequest`, `BonnieUnavailable`.

## Provisioning agents

`flag_commons.install.fastapi.install_router()` serves `GET /install.sh`
(the operator pipes it into `sudo bash -s --`) and `POST /agents/register`
(the script phones home). Supply a `token_lookup` that validates the
registration token and a `register` callback that creates the agent row.

## Testing against a real PostgreSQL

```bash
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/db poetry run pytest tests/integration
```

Without Postgres or Docker, `pip install pgserver` gives a local server:

```python
import pgserver, pathlib
print(pgserver.get_server(pathlib.Path("/tmp/pg")).get_uri())
```
