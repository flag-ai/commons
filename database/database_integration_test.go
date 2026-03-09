//go:build integration

package database_test

import (
	"context"
	"os"
	"testing"

	"github.com/flag-ai/commons/database"
	"github.com/stretchr/testify/require"
)

func TestNewPool_Integration(t *testing.T) {
	connStr := os.Getenv("TEST_DATABASE_URL")
	if connStr == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}

	ctx := context.Background()
	pool, err := database.NewPool(ctx, connStr, database.WithMaxConns(5))
	require.NoError(t, err)
	defer pool.Close()

	err = pool.Ping(ctx)
	require.NoError(t, err)
}
