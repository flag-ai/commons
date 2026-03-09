package secrets_test

import (
	"testing"

	"github.com/flag-ai/commons/secrets"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewProvider_Env(t *testing.T) {
	t.Parallel()

	p, err := secrets.NewProvider(secrets.ProviderEnv, nil)
	require.NoError(t, err)
	assert.NotNil(t, p)
}

func TestNewProvider_OpenBao(t *testing.T) {
	t.Run("missing addr", func(t *testing.T) {
		_, err := secrets.NewProvider(secrets.ProviderOpenBao, nil)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "OPENBAO_ADDR")
	})

	t.Run("missing token", func(t *testing.T) {
		t.Setenv("OPENBAO_ADDR", "http://localhost:8200")
		_, err := secrets.NewProvider(secrets.ProviderOpenBao, nil)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "OPENBAO_TOKEN")
	})

	t.Run("success", func(t *testing.T) {
		t.Setenv("OPENBAO_ADDR", "http://localhost:8200")
		t.Setenv("OPENBAO_TOKEN", "test-token")

		p, err := secrets.NewProvider(secrets.ProviderOpenBao, nil)
		require.NoError(t, err)
		assert.NotNil(t, p)
	})
}

func TestNewProvider_Unknown(t *testing.T) {
	t.Parallel()

	_, err := secrets.NewProvider("bogus", nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unknown provider")
}
