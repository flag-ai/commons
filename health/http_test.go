package health_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/flag-ai/commons/health"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestHTTPChecker_Healthy(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	c := health.NewHTTPChecker("test-svc", srv.URL)
	assert.Equal(t, "test-svc", c.Name())

	err := c.Check(context.Background())
	require.NoError(t, err)
}

func TestHTTPChecker_Unhealthy(t *testing.T) {
	t.Parallel()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	c := health.NewHTTPChecker("test-svc", srv.URL)
	err := c.Check(context.Background())

	require.Error(t, err)
	assert.Contains(t, err.Error(), "503")
}

func TestHTTPChecker_ConnectionRefused(t *testing.T) {
	t.Parallel()

	c := health.NewHTTPChecker("dead-svc", "http://localhost:1")
	err := c.Check(context.Background())

	require.Error(t, err)
	assert.Contains(t, err.Error(), "dead-svc")
}
