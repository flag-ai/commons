package health_test

import (
	"testing"

	"github.com/flag-ai/commons/health"
	"github.com/stretchr/testify/assert"
)

func TestDatabaseChecker_Name(t *testing.T) {
	t.Parallel()

	// Pass nil pool — we only test the Name() method here.
	// Actual connectivity is tested in integration tests.
	c := health.NewDatabaseChecker(nil)
	assert.Equal(t, "database", c.Name())
}
