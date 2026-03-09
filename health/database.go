package health

import (
	"context"

	"github.com/jackc/pgx/v5/pgxpool"
)

// DatabaseChecker checks PostgreSQL connectivity via a pgx pool.
type DatabaseChecker struct {
	pool *pgxpool.Pool
}

// NewDatabaseChecker creates a health checker for a PostgreSQL connection pool.
func NewDatabaseChecker(pool *pgxpool.Pool) *DatabaseChecker {
	return &DatabaseChecker{pool: pool}
}

// Name returns "database".
func (c *DatabaseChecker) Name() string {
	return "database"
}

// Check pings the database to verify connectivity.
func (c *DatabaseChecker) Check(ctx context.Context) error {
	return c.pool.Ping(ctx)
}
