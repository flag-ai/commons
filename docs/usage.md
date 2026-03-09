# Using flag-commons in FLAG Components

This guide covers how KARR, KITT, BONNIE, and future FLAG services import and use the commons library.

## Adding the Dependency

```bash
go get github.com/flag-ai/commons@latest
```

## Standard Initialization Pattern

Every FLAG component follows the same bootstrap sequence:

```go
package main

import (
    "context"
    "log"
    "os"

    "github.com/flag-ai/commons/config"
    "github.com/flag-ai/commons/database"
    "github.com/flag-ai/commons/health"
    "github.com/flag-ai/commons/logging"
    "github.com/flag-ai/commons/secrets"
    "github.com/flag-ai/commons/version"
)

func main() {
    ctx := context.Background()

    // 1. Secrets provider — OpenBao in production, env vars in dev
    provider, err := secrets.NewProvider(secrets.ProviderOpenBao, nil)
    if err != nil {
        provider = secrets.NewEnvProvider()
    }

    // 2. Base config — reads DATABASE_URL, LOG_LEVEL, LOG_FORMAT, LISTEN_ADDR
    cfg, err := config.LoadBase(ctx, "karr", provider)
    if err != nil {
        log.Fatal(err)
    }

    // 3. Logger — structured slog with component name and version
    logger := cfg.Logger()
    logger.Info("starting", "version", version.Info())

    // 4. Database pool
    pool, err := database.NewPool(ctx, cfg.DatabaseURL,
        database.WithPoolLogger(logger),
    )
    if err != nil {
        logger.Error("database connection failed", "error", err)
        os.Exit(1)
    }
    defer pool.Close()

    // 5. Migrations
    if err := database.RunMigrations("file://migrations", cfg.DatabaseURL, logger); err != nil {
        logger.Error("migration failed", "error", err)
        os.Exit(1)
    }

    // 6. Health checks
    reg := health.NewRegistry()
    reg.Register(health.NewDatabaseChecker(pool))

    // 7. Pass logger through context for request handlers
    ctx = logging.WithContext(ctx, logger)

    // ... start HTTP server on cfg.ListenAddr
}
```

## Package-by-Package Guide

### secrets — Retrieving Sensitive Values

The `secrets.Provider` interface is the single abstraction for reading secrets. Components never read secrets directly from env vars or OpenBao — they always go through a provider.

**Environment provider** (development):
```go
provider := secrets.NewEnvProvider()
dbURL, err := provider.Get(ctx, "DATABASE_URL")
port := provider.GetOrDefault(ctx, "PORT", "8080")
```

**OpenBao provider** (production):
```go
provider := secrets.NewOpenBaoProvider(
    "http://openbao.service:8200",
    token,
    secrets.WithMount("kv"),           // secrets engine mount
    secrets.WithLogger(logger),        // log cache misses
    secrets.WithCacheTTL(time.Minute), // override default 5m TTL
)

// Key format: "path#field" — field defaults to "value"
dbPass, err := provider.Get(ctx, "infra/postgres#password")
apiKey := provider.GetOrDefault(ctx, "infra/api-keys#openai", "")
```

**Factory** (auto-detect from environment):
```go
// Reads OPENBAO_ADDR and OPENBAO_TOKEN from environment
provider, err := secrets.NewProvider(secrets.ProviderOpenBao, logger)
```

### logging — Structured Logging

All FLAG components use `log/slog` via the commons logging package. This ensures consistent output with component name and version attached.

```go
// Create logger
logger := logging.New("karr",
    logging.WithLevel(logging.ParseLevel("debug")),
    logging.WithFormat(logging.FormatJSON),
)

// Propagate through context
ctx = logging.WithContext(ctx, logger)

// Retrieve in handlers/middleware
func handleRequest(ctx context.Context) {
    log := logging.FromContext(ctx)
    log.Info("handling request", "path", "/api/v1/models")
}
```

### config — Base Configuration

`config.LoadBase` reads environment variables through a `secrets.Provider`, so it works identically whether secrets come from env vars or OpenBao.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `LOG_LEVEL` | No | `info` | Minimum log level (debug, info, warn, error) |
| `LOG_FORMAT` | No | `text` | Log format (text, json) |
| `LISTEN_ADDR` | No | `:8080` | HTTP listen address |

Components that need additional config should embed `config.Base`:

```go
type KARRConfig struct {
    config.Base
    ModelRegistry string
    MaxWorkers    int
}
```

### database — Connection Pooling & Migrations

**Pool creation** with functional options:
```go
pool, err := database.NewPool(ctx, cfg.DatabaseURL,
    database.WithMaxConns(20),
    database.WithMinConns(5),
    database.WithMaxConnLifetime(30 * time.Minute),
    database.WithMaxConnIdleTime(5 * time.Minute),
    database.WithHealthCheckPeriod(30 * time.Second),
    database.WithPoolLogger(logger),
)
```

Note: `NewPool` returns a lazily-connected pool. Call `pool.Ping(ctx)` after creation if you need to verify connectivity immediately.

**Migrations** using golang-migrate file source:
```go
// migrations/ directory contains 001_init.up.sql, 001_init.down.sql, etc.
err := database.RunMigrations("file://migrations", cfg.DatabaseURL, logger)
```

### health — Health Check Registry

Register checkers and run them concurrently:

```go
reg := health.NewRegistry()
reg.Register(health.NewDatabaseChecker(pool))
reg.Register(health.NewHTTPChecker("model-api", "http://localhost:8081/health"))

// In your health endpoint handler:
func healthHandler(w http.ResponseWriter, r *http.Request) {
    report := reg.RunAll(r.Context())
    w.Header().Set("Content-Type", "application/json")
    if !report.Healthy {
        w.WriteHeader(http.StatusServiceUnavailable)
    }
    json.NewEncoder(w).Encode(report)
}
```

Response format:
```json
{
    "healthy": true,
    "version": "1.0.0 (commit: abc123, built: 2025-06-01)",
    "checks": [
        {"name": "database", "healthy": true, "latency_ms": 2},
        {"name": "model-api", "healthy": true, "latency_ms": 15}
    ]
}
```

**Custom checkers** implement the `health.Checker` interface:
```go
type RedisChecker struct {
    client *redis.Client
}

func (c *RedisChecker) Name() string { return "redis" }
func (c *RedisChecker) Check(ctx context.Context) error {
    return c.client.Ping(ctx).Err()
}
```

### version — Build-Time Info

Set via ldflags in your Makefile or CI:

```bash
go build -ldflags "\
  -X github.com/flag-ai/commons/version.Version=$(git describe --tags) \
  -X github.com/flag-ai/commons/version.Commit=$(git rev-parse --short HEAD) \
  -X github.com/flag-ai/commons/version.Date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

Access in code:
```go
fmt.Println(version.Info())
// "1.0.0 (commit: abc123, built: 2025-06-01T12:00:00Z)"
```

## Dependency Graph

```
version/     → (no deps, leaf)
secrets/     → accepts *slog.Logger param
logging/     → imports version/
config/      → imports secrets/, logging/
database/    → imports logging/; external: pgx/v5, golang-migrate
health/      → imports version/; accepts *pgxpool.Pool param
```

No circular dependencies. If you add a new package, check that it doesn't introduce cycles.

## Testing with Commons

Use `t.Setenv` for tests that need environment variables:

```go
func TestMyHandler(t *testing.T) {
    t.Setenv("DATABASE_URL", "postgres://localhost/testdb")

    provider := secrets.NewEnvProvider()
    cfg, err := config.LoadBase(context.Background(), "test", provider)
    require.NoError(t, err)
    // ...
}
```

For OpenBao tests, use `httptest.Server` returning KV v2 JSON:

```go
srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
    resp := map[string]interface{}{
        "data": map[string]interface{}{
            "data": map[string]interface{}{"value": "test-secret"},
        },
    }
    json.NewEncoder(w).Encode(resp)
}))
defer srv.Close()

provider := secrets.NewOpenBaoProvider(srv.URL, "test-token")
```
