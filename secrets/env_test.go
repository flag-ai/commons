package secrets_test

import (
	"context"
	"testing"

	"github.com/flag-ai/commons/secrets"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestEnvProvider_Get(t *testing.T) {
	p := secrets.NewEnvProvider()
	ctx := context.Background()

	t.Run("existing variable", func(t *testing.T) {
		t.Setenv("FLAG_TEST_SECRET", "hunter2")

		val, err := p.Get(ctx, "FLAG_TEST_SECRET")
		require.NoError(t, err)
		assert.Equal(t, "hunter2", val)
	})

	t.Run("missing variable", func(t *testing.T) {
		_, err := p.Get(ctx, "FLAG_TEST_DEFINITELY_NOT_SET_12345")
		require.Error(t, err)
		assert.Contains(t, err.Error(), "not set")
	})
}

func TestEnvProvider_GetOrDefault(t *testing.T) {
	p := secrets.NewEnvProvider()
	ctx := context.Background()

	t.Run("existing variable", func(t *testing.T) {
		t.Setenv("FLAG_TEST_DEFAULT", "real_value")

		val := p.GetOrDefault(ctx, "FLAG_TEST_DEFAULT", "fallback")
		assert.Equal(t, "real_value", val)
	})

	t.Run("missing variable returns default", func(t *testing.T) {
		val := p.GetOrDefault(ctx, "FLAG_TEST_DEFINITELY_NOT_SET_67890", "fallback")
		assert.Equal(t, "fallback", val)
	})
}
