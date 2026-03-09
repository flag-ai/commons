package logging_test

import (
	"bytes"
	"context"
	"log/slog"
	"testing"

	"github.com/flag-ai/commons/logging"
	"github.com/stretchr/testify/assert"
)

func TestWithContext_FromContext(t *testing.T) {
	t.Parallel()

	var buf bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&buf, nil))

	ctx := logging.WithContext(context.Background(), logger)
	retrieved := logging.FromContext(ctx)

	retrieved.Info("from context")
	assert.Contains(t, buf.String(), "from context")
}

func TestFromContext_Default(t *testing.T) {
	t.Parallel()

	logger := logging.FromContext(context.Background())
	assert.NotNil(t, logger)
}
