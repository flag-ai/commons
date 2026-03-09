package config_test

import (
	"context"
	"testing"

	"github.com/flag-ai/commons/config"
	"github.com/flag-ai/commons/secrets"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLoadBase(t *testing.T) {
	ctx := context.Background()

	t.Run("success with defaults", func(t *testing.T) {
		t.Setenv("DATABASE_URL", "postgres://localhost/flagdb")

		p := secrets.NewEnvProvider()
		cfg, err := config.LoadBase(ctx, "karr", p)
		require.NoError(t, err)
		assert.Equal(t, "karr", cfg.Component)
		assert.Equal(t, "info", cfg.LogLevel)
		assert.Equal(t, "text", cfg.LogFormat)
		assert.Equal(t, "postgres://localhost/flagdb", cfg.DatabaseURL)
		assert.Equal(t, ":8080", cfg.ListenAddr)
	})

	t.Run("custom values", func(t *testing.T) {
		t.Setenv("DATABASE_URL", "postgres://localhost/flagdb")
		t.Setenv("LOG_LEVEL", "debug")
		t.Setenv("LOG_FORMAT", "json")
		t.Setenv("LISTEN_ADDR", ":9090")

		p := secrets.NewEnvProvider()
		cfg, err := config.LoadBase(ctx, "kitt", p)
		require.NoError(t, err)
		assert.Equal(t, "debug", cfg.LogLevel)
		assert.Equal(t, "json", cfg.LogFormat)
		assert.Equal(t, ":9090", cfg.ListenAddr)
	})

	t.Run("missing DATABASE_URL", func(t *testing.T) {
		p := secrets.NewEnvProvider()
		_, err := config.LoadBase(ctx, "karr", p)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "DATABASE_URL")
	})

	t.Run("empty component", func(t *testing.T) {
		p := secrets.NewEnvProvider()
		_, err := config.LoadBase(ctx, "", p)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "component name")
	})
}

func TestBase_Logger(t *testing.T) {
	t.Parallel()

	cfg := &config.Base{
		Component: "test",
		LogLevel:  "debug",
		LogFormat: "json",
	}
	logger := cfg.Logger()
	assert.NotNil(t, logger)
}
