package database_test

import (
	"testing"

	"github.com/flag-ai/commons/database"
	"github.com/stretchr/testify/assert"
)

func TestRunMigrations_BadSource(t *testing.T) {
	t.Parallel()

	err := database.RunMigrations("file:///nonexistent/path", "postgres://localhost/testdb", nil)
	assert.Error(t, err)
}
