package health_test

import (
	"context"
	"errors"
	"testing"

	"github.com/flag-ai/commons/health"
	"github.com/stretchr/testify/assert"
)

type mockChecker struct {
	name string
	err  error
}

func (m *mockChecker) Name() string                  { return m.name }
func (m *mockChecker) Check(_ context.Context) error { return m.err }

func TestRegistry_Empty(t *testing.T) {
	t.Parallel()

	reg := health.NewRegistry()
	report := reg.RunAll(context.Background())

	assert.True(t, report.Healthy)
	assert.Empty(t, report.Checks)
}

func TestRegistry_AllHealthy(t *testing.T) {
	t.Parallel()

	reg := health.NewRegistry()
	reg.Register(&mockChecker{name: "db"})
	reg.Register(&mockChecker{name: "cache"})

	report := reg.RunAll(context.Background())

	assert.True(t, report.Healthy)
	assert.Len(t, report.Checks, 2)
	for _, s := range report.Checks {
		assert.True(t, s.Healthy)
		assert.Empty(t, s.Error)
	}
}

func TestRegistry_OneUnhealthy(t *testing.T) {
	t.Parallel()

	reg := health.NewRegistry()
	reg.Register(&mockChecker{name: "db"})
	reg.Register(&mockChecker{name: "cache", err: errors.New("connection refused")})

	report := reg.RunAll(context.Background())

	assert.False(t, report.Healthy)
	assert.Len(t, report.Checks, 2)

	var unhealthy int
	for _, s := range report.Checks {
		if !s.Healthy {
			unhealthy++
			assert.Contains(t, s.Error, "connection refused")
		}
	}
	assert.Equal(t, 1, unhealthy)
}

func TestRegistry_ConcurrentRegister(t *testing.T) {
	t.Parallel()

	reg := health.NewRegistry()
	done := make(chan struct{})

	go func() {
		for range 100 {
			reg.Register(&mockChecker{name: "concurrent"})
		}
		close(done)
	}()

	// Run checks while registering
	for range 10 {
		reg.RunAll(context.Background())
	}
	<-done
}
