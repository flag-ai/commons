# FLAG Commons

Shared Go library for the FLAG (Foundation for Local AI Governance) platform. Provides foundational contracts used by all FLAG components (KARR, KITT, BONNIE).

## Packages

| Package | Description |
|---------|-------------|
| `version` | Build-time version info via ldflags |
| `secrets` | Unified secrets interface (env vars, OpenBao) |
| `logging` | Structured logging with slog, context propagation |
| `config` | Base configuration loading from secrets providers |
| `database` | PostgreSQL connection pooling (pgx/v5) and migrations |
| `health` | Health check registry with concurrent execution |

## Installation

```bash
go get github.com/flag-ai/commons
```

## Quick Start

```go
package main

import (
    "context"

    "github.com/flag-ai/commons/config"
    "github.com/flag-ai/commons/health"
    "github.com/flag-ai/commons/secrets"
)

func main() {
    ctx := context.Background()

    // Load secrets from environment
    provider := secrets.NewEnvProvider()

    // Load base config
    cfg, err := config.LoadBase(ctx, "my-service", provider)
    if err != nil {
        panic(err)
    }

    // Create logger
    logger := cfg.Logger()
    logger.Info("starting service")

    // Set up health checks
    reg := health.NewRegistry()
    reg.Register(health.NewHTTPChecker("dependency", "http://localhost:8081/health"))

    report := reg.RunAll(ctx)
    logger.Info("health check complete", "healthy", report.Healthy)
}
```

## Version Injection

Set version info at build time:

```bash
go build -ldflags "\
  -X github.com/flag-ai/commons/version.Version=1.0.0 \
  -X github.com/flag-ai/commons/version.Commit=$(git rev-parse --short HEAD) \
  -X github.com/flag-ai/commons/version.Date=$(date -u +%Y-%m-%d)"
```

## Secrets Providers

### Environment Variables

```go
provider := secrets.NewEnvProvider()
val, err := provider.Get(ctx, "DATABASE_URL")
```

### OpenBao

```go
provider := secrets.NewOpenBaoProvider(
    "http://openbao:8200",
    token,
    secrets.WithMount("kv"),
    secrets.WithLogger(logger),
)

// Key format: "path#field" (field defaults to "value")
password, err := provider.Get(ctx, "db/credentials#password")
```

### Factory

```go
// Auto-configure from OPENBAO_ADDR and OPENBAO_TOKEN env vars
provider, err := secrets.NewProvider(secrets.ProviderOpenBao, logger)
```

## Database

```go
pool, err := database.NewPool(ctx, connStr,
    database.WithMaxConns(20),
    database.WithMinConns(5),
    database.WithPoolLogger(logger),
)

// Run migrations
err = database.RunMigrations("file://migrations", connStr, logger)
```

## Health Checks

```go
reg := health.NewRegistry()
reg.Register(health.NewDatabaseChecker(pool))
reg.Register(health.NewHTTPChecker("api", "http://localhost:8080/health"))

report := reg.RunAll(ctx) // Runs all checks concurrently
// report.Healthy, report.Checks, report.Version
```

## Development

```bash
# Run tests
go test -race ./...

# Run linter
golangci-lint run ./...

# Run integration tests (requires PostgreSQL)
TEST_DATABASE_URL=postgres://... go test -race -tags=integration ./...
```

## License

Apache 2.0
