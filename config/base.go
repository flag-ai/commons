// Package config provides base configuration loading for FLAG components.
package config

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/flag-ai/commons/logging"
	"github.com/flag-ai/commons/secrets"
)

// Base holds configuration common to all FLAG components.
type Base struct {
	// Component name (e.g., "karr", "kitt", "bonnie").
	Component string

	// LogLevel is the minimum log level (debug, info, warn, error).
	LogLevel string

	// LogFormat is the log output format (text, json).
	LogFormat string

	// DatabaseURL is the PostgreSQL connection string.
	DatabaseURL string

	// ListenAddr is the HTTP listen address (e.g., ":8080").
	ListenAddr string
}

// LoadBase builds a Base config by reading environment variables via the given secrets provider.
// It uses sensible defaults where appropriate.
func LoadBase(ctx context.Context, component string, provider secrets.Provider) (*Base, error) {
	if component == "" {
		return nil, fmt.Errorf("config: component name is required")
	}

	dbURL, err := provider.Get(ctx, "DATABASE_URL")
	if err != nil {
		return nil, fmt.Errorf("config: DATABASE_URL is required: %w", err)
	}

	return &Base{
		Component:   component,
		LogLevel:    provider.GetOrDefault(ctx, "LOG_LEVEL", "info"),
		LogFormat:   provider.GetOrDefault(ctx, "LOG_FORMAT", "text"),
		DatabaseURL: dbURL,
		ListenAddr:  provider.GetOrDefault(ctx, "LISTEN_ADDR", ":8080"),
	}, nil
}

// Logger creates a configured logger from the base config.
func (b *Base) Logger() *slog.Logger {
	return logging.New(b.Component,
		logging.WithLevel(logging.ParseLevel(b.LogLevel)),
		logging.WithFormat(logging.Format(b.LogFormat)),
	)
}
