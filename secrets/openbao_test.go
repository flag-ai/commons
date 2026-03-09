package secrets_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/flag-ai/commons/secrets"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func newTestBaoServer(t *testing.T, data map[string]interface{}) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Vault-Token") != "test-token" {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}

		resp := map[string]interface{}{
			"data": map[string]interface{}{
				"data": data,
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestOpenBaoProvider_Get_DefaultField(t *testing.T) {
	t.Parallel()

	srv := newTestBaoServer(t, map[string]interface{}{
		"value":    "secret-password",
		"username": "admin",
	})

	p := secrets.NewOpenBaoProvider(srv.URL, "test-token")
	val, err := p.Get(context.Background(), "db/credentials")
	require.NoError(t, err)
	assert.Equal(t, "secret-password", val)
}

func TestOpenBaoProvider_Get_ExplicitField(t *testing.T) {
	t.Parallel()

	srv := newTestBaoServer(t, map[string]interface{}{
		"value":    "secret-password",
		"username": "admin",
	})

	p := secrets.NewOpenBaoProvider(srv.URL, "test-token")
	val, err := p.Get(context.Background(), "db/credentials#username")
	require.NoError(t, err)
	assert.Equal(t, "admin", val)
}

func TestOpenBaoProvider_Get_MissingField(t *testing.T) {
	t.Parallel()

	srv := newTestBaoServer(t, map[string]interface{}{
		"value": "secret-password",
	})

	p := secrets.NewOpenBaoProvider(srv.URL, "test-token")
	_, err := p.Get(context.Background(), "db/credentials#nonexistent")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")
}

func TestOpenBaoProvider_Get_BadToken(t *testing.T) {
	t.Parallel()

	srv := newTestBaoServer(t, nil)

	p := secrets.NewOpenBaoProvider(srv.URL, "wrong-token")
	_, err := p.Get(context.Background(), "anything")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "403")
}

func TestOpenBaoProvider_Get_Caching(t *testing.T) {
	t.Parallel()

	callCount := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		callCount++
		resp := map[string]interface{}{
			"data": map[string]interface{}{
				"data": map[string]interface{}{"value": "cached-secret"},
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	t.Cleanup(srv.Close)

	p := secrets.NewOpenBaoProvider(srv.URL, "test-token")
	ctx := context.Background()

	val1, err := p.Get(ctx, "test/path")
	require.NoError(t, err)
	assert.Equal(t, "cached-secret", val1)

	val2, err := p.Get(ctx, "test/path")
	require.NoError(t, err)
	assert.Equal(t, "cached-secret", val2)

	assert.Equal(t, 1, callCount, "second call should use cache")
}

func TestOpenBaoProvider_GetOrDefault_Success(t *testing.T) {
	t.Parallel()

	srv := newTestBaoServer(t, map[string]interface{}{"value": "real"})

	p := secrets.NewOpenBaoProvider(srv.URL, "test-token")
	val := p.GetOrDefault(context.Background(), "test/secret", "default")
	assert.Equal(t, "real", val)
}

func TestOpenBaoProvider_GetOrDefault_Fallback(t *testing.T) {
	t.Parallel()

	p := secrets.NewOpenBaoProvider("http://localhost:1", "token")
	val := p.GetOrDefault(context.Background(), "test/secret", "default")
	assert.Equal(t, "default", val)
}

func TestOpenBaoProvider_Get_EmptyKey(t *testing.T) {
	t.Parallel()

	p := secrets.NewOpenBaoProvider("http://localhost:1", "token")
	_, err := p.Get(context.Background(), "")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "empty key")
}

func TestOpenBaoProvider_Get_EmptyPath(t *testing.T) {
	t.Parallel()

	p := secrets.NewOpenBaoProvider("http://localhost:1", "token")
	_, err := p.Get(context.Background(), "#field")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "empty path")
}

func TestOpenBaoProvider_Get_EmptyField(t *testing.T) {
	t.Parallel()

	p := secrets.NewOpenBaoProvider("http://localhost:1", "token")
	_, err := p.Get(context.Background(), "path#")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "empty field")
}

func TestOpenBaoProvider_WithMount(t *testing.T) {
	t.Parallel()

	var receivedPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		resp := map[string]interface{}{
			"data": map[string]interface{}{
				"data": map[string]interface{}{"value": "ok"},
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	t.Cleanup(srv.Close)

	p := secrets.NewOpenBaoProvider(srv.URL, "token", secrets.WithMount("secret"))
	_, err := p.Get(context.Background(), "my/path")
	require.NoError(t, err)
	assert.Equal(t, "/v1/secret/data/my/path", receivedPath)
}
