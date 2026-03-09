// Package database provides PostgreSQL connection pooling and migration utilities
// for FLAG components.
package database

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// PoolOption configures a connection pool.
type PoolOption func(*poolConfig)

type poolConfig struct {
	maxConns          int32
	minConns          int32
	maxConnLifetime   time.Duration
	maxConnIdleTime   time.Duration
	healthCheckPeriod time.Duration
	logger            *slog.Logger
}

// WithMaxConns sets the maximum number of connections in the pool.
func WithMaxConns(n int32) PoolOption {
	return func(c *poolConfig) {
		c.maxConns = n
	}
}

// WithMinConns sets the minimum number of connections maintained in the pool.
func WithMinConns(n int32) PoolOption {
	return func(c *poolConfig) {
		c.minConns = n
	}
}

// WithMaxConnLifetime sets the maximum lifetime of a connection.
func WithMaxConnLifetime(d time.Duration) PoolOption {
	return func(c *poolConfig) {
		c.maxConnLifetime = d
	}
}

// WithMaxConnIdleTime sets the maximum idle time before a connection is closed.
func WithMaxConnIdleTime(d time.Duration) PoolOption {
	return func(c *poolConfig) {
		c.maxConnIdleTime = d
	}
}

// WithHealthCheckPeriod sets how often idle connections are checked.
func WithHealthCheckPeriod(d time.Duration) PoolOption {
	return func(c *poolConfig) {
		c.healthCheckPeriod = d
	}
}

// WithPoolLogger sets the logger for pool events.
func WithPoolLogger(logger *slog.Logger) PoolOption {
	return func(c *poolConfig) {
		c.logger = logger
	}
}

// NewPool creates a new pgx connection pool with the given options.
func NewPool(ctx context.Context, connStr string, opts ...PoolOption) (*pgxpool.Pool, error) {
	cfg := &poolConfig{
		maxConns:          10,
		minConns:          2,
		maxConnLifetime:   30 * time.Minute,
		maxConnIdleTime:   5 * time.Minute,
		healthCheckPeriod: 30 * time.Second,
	}
	for _, opt := range opts {
		opt(cfg)
	}

	poolCfg, err := pgxpool.ParseConfig(connStr)
	if err != nil {
		return nil, fmt.Errorf("database: invalid connection string: %w", err)
	}

	poolCfg.MaxConns = cfg.maxConns
	poolCfg.MinConns = cfg.minConns
	poolCfg.MaxConnLifetime = cfg.maxConnLifetime
	poolCfg.MaxConnIdleTime = cfg.maxConnIdleTime
	poolCfg.HealthCheckPeriod = cfg.healthCheckPeriod

	pool, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		return nil, fmt.Errorf("database: failed to create pool: %w", err)
	}

	if cfg.logger != nil {
		cfg.logger.Info("database pool created",
			"max_conns", cfg.maxConns,
			"min_conns", cfg.minConns,
		)
	}

	return pool, nil
}
