# Changelog

## 0.3.0

The library is now Python. The Go implementation is preserved unchanged at
tag `go-final-v0.2.1` (identical to `v0.2.1`); Go consumers keep pinning
`v0.2.1`. BONNIE, which stays in Go, vendored the four packages it uses
(`secrets`, `logging`, `health`, `version`) before this release.

Every Go package has a Python counterpart with every Go test case ported.
Behaviour changes, all deliberate:

- **secrets:** `ChainProvider` resolves each key through env first and
  OpenBao second, replacing the Go mode that sent every key to OpenBao.
  OpenBao paths keep real slashes (dot segments rejected); backend errors
  fall back to the default with a WARNING. `SecretsProvider` is synchronous.
- **config:** an empty `DATABASE_URL` is rejected when required;
  `require_database=False` for components without a database;
  `database_url` is a `SecretStr`; `bind_address()` for uvicorn.
- **logging:** configures the stdlib root logger with slog-compatible text
  and JSON formatters; `bind()` replaces the Go context helpers.
- **version:** the version comes from `importlib.metadata`, the commit and
  date from `FLAG_BUILD_COMMIT` / `FLAG_BUILD_DATE`; the
  `"X (commit: Y, built: Z)"` string is unchanged.
- **health:** per-check timeout, exceptions captured as failed checks,
  duplicate names rejected, non-critical checks, and a FastAPI router for the
  standard `/health` + `/ready` contract. The report JSON is byte-compatible.
- **database:** SQLAlchemy 2 + psycopg 3 engines with a startup ping and
  backoff; Alembic migrations under `pg_advisory_lock` with a lock timeout.
  The version table is Alembic's, not golang-migrate's.
- **bonnie:** tolerant SSE parser for BONNIE's raw multi-line frames and
  stdcopy headers; `disk`/`gpus` null stay `None`; `fetch_model` has its own
  long timeout and is not retried on timeout; no sleep after the final retry;
  `Retry-After` clamped; registry polls immediately, concurrently, reloads
  periodically, and distinguishes `unauthorized` from `offline`.
- **install:** every templated value is shell-quoted and the server URL is
  validated; `X-Forwarded-For` is trusted only from configured proxies; the
  systemd unit gains `StateDirectory=bonnie`.

Dropped: `internal/testutil`.

## 0.2.1

Last Go release. See tag `go-final-v0.2.1`.
