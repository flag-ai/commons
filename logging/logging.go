// Package logging provides structured logging setup for FLAG components.
package logging

import (
	"io"
	"log/slog"
	"os"
	"strings"

	"github.com/flag-ai/commons/version"
)

// Format selects the log output format.
type Format string

const (
	FormatText Format = "text"
	FormatJSON Format = "json"
)

// Option configures a logger.
type Option func(*options)

type options struct {
	level  slog.Level
	format Format
	output io.Writer
}

// WithLevel sets the minimum log level.
func WithLevel(level slog.Level) Option {
	return func(o *options) {
		o.level = level
	}
}

// WithFormat sets the output format (text or json).
func WithFormat(format Format) Option {
	return func(o *options) {
		o.format = format
	}
}

// WithOutput sets the output writer (default: os.Stderr).
func WithOutput(w io.Writer) Option {
	return func(o *options) {
		o.output = w
	}
}

// New creates a new structured logger with version information attached.
func New(component string, opts ...Option) *slog.Logger {
	cfg := &options{
		level:  slog.LevelInfo,
		format: FormatText,
		output: os.Stderr,
	}
	for _, opt := range opts {
		opt(cfg)
	}

	handlerOpts := &slog.HandlerOptions{Level: cfg.level}

	var handler slog.Handler
	switch cfg.format {
	case FormatJSON:
		handler = slog.NewJSONHandler(cfg.output, handlerOpts)
	default:
		handler = slog.NewTextHandler(cfg.output, handlerOpts)
	}

	return slog.New(handler).With(
		"component", component,
		"version", version.Version,
	)
}

// ParseLevel converts a string level name to slog.Level.
// Accepted values: debug, info, warn, error. Defaults to info.
func ParseLevel(s string) slog.Level {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "debug":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}
