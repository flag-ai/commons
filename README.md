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
| `bonnie` | HTTP client + agent registry for BONNIE services |

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

## Logging

```go
// Create a structured logger
logger := logging.New("karr",
    logging.WithLevel(slog.LevelDebug),
    logging.WithFormat(logging.FormatJSON),
)

// Parse level from string (e.g., from config)
level := logging.ParseLevel("debug") // returns slog.LevelDebug

// Context propagation
ctx = logging.WithContext(ctx, logger)

// Later, retrieve logger from context
log := logging.FromContext(ctx) // falls back to slog.Default() if unset
log.Info("processing request", "id", requestID)
```

## Config

```go
// LoadBase reads common config via a secrets provider
provider := secrets.NewEnvProvider()
cfg, err := config.LoadBase(ctx, "karr", provider)

// Reads these env vars (with defaults):
//   DATABASE_URL  — required, no default
//   LOG_LEVEL     — default: "info"
//   LOG_FORMAT    — default: "text"
//   LISTEN_ADDR   — default: ":8080"

// Create a logger from config
logger := cfg.Logger()
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

## BONNIE Client

```go
client := bonnie.New("http://gpu-01:8000", token,
    bonnie.WithLogger(logger),
    bonnie.WithRetries(3),
)
snap, err := client.GPUStatus(ctx)
```

Use `bonnie.NewRegistry(store, 30*time.Second, logger)` to manage a set
of agents with background health polling; `store` is any type that
implements `bonnie.RegistryStore`.

## Full Component Bootstrap

This is the standard pattern for initializing a FLAG component:

```go
func main() {
    ctx := context.Background()

    // 1. Set up secrets provider (OpenBao in production, env in dev)
    provider, err := secrets.NewProvider(secrets.ProviderOpenBao, nil)
    if err != nil {
        // Fall back to env vars in development
        provider = secrets.NewEnvProvider()
    }

    // 2. Load base configuration
    cfg, err := config.LoadBase(ctx, "karr", provider)
    if err != nil {
        log.Fatal(err)
    }

    // 3. Create logger
    logger := cfg.Logger()
    logger.Info("starting", "version", version.Info())

    // 4. Connect to database
    pool, err := database.NewPool(ctx, cfg.DatabaseURL,
        database.WithMaxConns(20),
        database.WithPoolLogger(logger),
    )
    if err != nil {
        logger.Error("database connection failed", "error", err)
        os.Exit(1)
    }
    defer pool.Close()

    // 5. Run migrations
    if err := database.RunMigrations("file://migrations", cfg.DatabaseURL, logger); err != nil {
        logger.Error("migration failed", "error", err)
        os.Exit(1)
    }

    // 6. Register health checks
    reg := health.NewRegistry()
    reg.Register(health.NewDatabaseChecker(pool))

    // 7. Use context-propagated logger in handlers
    ctx = logging.WithContext(ctx, logger)
}
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
