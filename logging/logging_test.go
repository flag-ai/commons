package logging_test

import (
	"bytes"
	"log/slog"
	"testing"

	"github.com/flag-ai/commons/logging"
	"github.com/stretchr/testify/assert"
)

func TestNew_TextFormat(t *testing.T) {
	t.Parallel()

	var buf bytes.Buffer
	logger := logging.New("test-svc", logging.WithOutput(&buf), logging.WithFormat(logging.FormatText))

	logger.Info("hello")
	assert.Contains(t, buf.String(), "component=test-svc")
	assert.Contains(t, buf.String(), "hello")
}

func TestNew_JSONFormat(t *testing.T) {
	t.Parallel()

	var buf bytes.Buffer
	logger := logging.New("test-svc", logging.WithOutput(&buf), logging.WithFormat(logging.FormatJSON))

	logger.Info("hello")
	assert.Contains(t, buf.String(), `"component":"test-svc"`)
	assert.Contains(t, buf.String(), `"msg":"hello"`)
}

func TestNew_LevelFiltering(t *testing.T) {
	t.Parallel()

	var buf bytes.Buffer
	logger := logging.New("test-svc",
		logging.WithOutput(&buf),
		logging.WithLevel(slog.LevelWarn),
	)

	logger.Info("should not appear")
	assert.Empty(t, buf.String())

	logger.Warn("should appear")
	assert.Contains(t, buf.String(), "should appear")
}

func TestParseLevel(t *testing.T) {
	t.Parallel()

	tests := []struct {
		input    string
		expected slog.Level
	}{
		{"debug", slog.LevelDebug},
		{"DEBUG", slog.LevelDebug},
		{"info", slog.LevelInfo},
		{"warn", slog.LevelWarn},
		{"warning", slog.LevelWarn},
		{"error", slog.LevelError},
		{"unknown", slog.LevelInfo},
		{"", slog.LevelInfo},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			t.Parallel()
			assert.Equal(t, tt.expected, logging.ParseLevel(tt.input))
		})
	}
}
