package health_test

import (
	"context"
	"testing"

	"github.com/flag-ai/commons/health"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestDatabaseChecker_Name(t *testing.T) {
	t.Parallel()

	c := health.NewDatabaseChecker(nil)
	assert.Equal(t, "database", c.Name())
}

func TestDatabaseChecker_NilPool(t *testing.T) {
	t.Parallel()

	c := health.NewDatabaseChecker(nil)
	err := c.Check(context.Background())
	require.Error(t, err)
	assert.Contains(t, err.Error(), "nil")
}
