package database_test

import (
	"testing"
	"time"

	"github.com/flag-ai/commons/database"
	"github.com/stretchr/testify/assert"
)

func TestPoolOptions(t *testing.T) {
	t.Parallel()

	// Verify options don't panic when applied. Actual pool creation
	// requires a live database, tested in integration tests.
	opts := []database.PoolOption{
		database.WithMaxConns(20),
		database.WithMinConns(5),
		database.WithMaxConnLifetime(1 * time.Hour),
		database.WithMaxConnIdleTime(10 * time.Minute),
		database.WithHealthCheckPeriod(1 * time.Minute),
		database.WithPoolLogger(nil),
	}
	assert.Len(t, opts, 6)
}

func TestNewPool_InvalidConnString(t *testing.T) {
	t.Parallel()

	// A completely bogus connection string should fail at parse time.
	_, err := database.NewPool(t.Context(), "not://a-valid-url:::broken")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "invalid connection string")
}
