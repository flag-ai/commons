package bonnie_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/flag-ai/commons/bonnie"
)

// fakeStore is a minimal in-memory RegistryStore used across the registry
// tests. It records every UpdateStatus call for assertions.
type fakeStore struct {
	mu       sync.Mutex
	agents   []bonnie.Agent
	updates  []statusUpdate
	listErr  error
	updErr   error
	updCalls atomic.Int32
}

type statusUpdate struct {
	ID         string
	Status     string
	LastSeenAt time.Time
}

func (s *fakeStore) List(_ context.Context) ([]bonnie.Agent, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.listErr != nil {
		return nil, s.listErr
	}
	out := make([]bonnie.Agent, len(s.agents))
	copy(out, s.agents)
	return out, nil
}

func (s *fakeStore) UpdateStatus(_ context.Context, id, status string, lastSeenAt time.Time) error {
	s.updCalls.Add(1)
	if s.updErr != nil {
		return s.updErr
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.updates = append(s.updates, statusUpdate{ID: id, Status: status, LastSeenAt: lastSeenAt})
	return nil
}

func (s *fakeStore) setAgents(a []bonnie.Agent) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.agents = append(s.agents[:0], a...)
}

func (s *fakeStore) snapshotUpdates() []statusUpdate {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]statusUpdate, len(s.updates))
	copy(out, s.updates)
	return out
}

// okServer returns an httptest.Server whose /health handler always
// returns 200. Callers that need different codes create servers inline.
func okServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestRegistry_ReloadAndGet(t *testing.T) {
	t.Parallel()
	srv := okServer(t)
	store := &fakeStore{}
	store.setAgents([]bonnie.Agent{
		{ID: "a", Name: "agent-a", URL: srv.URL, Token: "tok"},
	})

	reg := bonnie.NewRegistry(store, 0, discardLogger())
	require.NoError(t, reg.Reload(context.Background()))

	client, ok := reg.Get("a")
	require.True(t, ok)
	require.NotNil(t, client)
	require.NoError(t, client.Health(context.Background()))
}

func TestRegistry_Get_Missing(t *testing.T) {
	t.Parallel()
	reg := bonnie.NewRegistry(&fakeStore{}, 0, discardLogger())
	require.NoError(t, reg.Reload(context.Background()))
	_, ok := reg.Get("missing")
	assert.False(t, ok)
}

func TestRegistry_All(t *testing.T) {
	t.Parallel()
	srv := okServer(t)
	store := &fakeStore{}
	store.setAgents([]bonnie.Agent{
		{ID: "a", URL: srv.URL, Token: "tok-a"},
		{ID: "b", URL: srv.URL, Token: "tok-b"},
	})

	reg := bonnie.NewRegistry(store, 0, discardLogger())
	require.NoError(t, reg.Reload(context.Background()))

	all := reg.All()
	require.Len(t, all, 2)
	assert.NotNil(t, all["a"])
	assert.NotNil(t, all["b"])
}

func TestRegistry_Upsert(t *testing.T) {
	t.Parallel()
	srv := okServer(t)
	reg := bonnie.NewRegistry(&fakeStore{}, 0, discardLogger())
	reg.Upsert(bonnie.Agent{ID: "a", URL: srv.URL, Token: "tok"})

	client, ok := reg.Get("a")
	require.True(t, ok)
	require.NotNil(t, client)
}

func TestRegistry_Remove(t *testing.T) {
	t.Parallel()
	reg := bonnie.NewRegistry(&fakeStore{}, 0, discardLogger())
	reg.Upsert(bonnie.Agent{ID: "a", URL: "http://x"})
	reg.Remove("a")
	_, ok := reg.Get("a")
	assert.False(t, ok)
}

func TestRegistry_ReloadPreservesExistingClient(t *testing.T) {
	t.Parallel()
	srv := okServer(t)
	store := &fakeStore{}
	store.setAgents([]bonnie.Agent{
		{ID: "a", URL: srv.URL, Token: "tok"},
	})

	reg := bonnie.NewRegistry(store, 0, discardLogger())
	require.NoError(t, reg.Reload(context.Background()))
	first, _ := reg.Get("a")

	// Reload with the same URL+Token — client identity must be preserved.
	require.NoError(t, reg.Reload(context.Background()))
	second, _ := reg.Get("a")
	assert.Same(t, first, second)

	// Change the token — a new client should be created.
	store.setAgents([]bonnie.Agent{
		{ID: "a", URL: srv.URL, Token: "tok-2"},
	})
	require.NoError(t, reg.Reload(context.Background()))
	third, _ := reg.Get("a")
	assert.NotSame(t, first, third)
}

func TestRegistry_Poll_OnlineAndOffline(t *testing.T) {
	t.Parallel()
	online := okServer(t)

	// Create an offline server and close it so connections fail.
	offlineSrv := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, _ *http.Request) {}))
	offlineURL := offlineSrv.URL
	offlineSrv.Close()

	store := &fakeStore{}
	store.setAgents([]bonnie.Agent{
		{ID: "online", URL: online.URL, Token: "t"},
		{ID: "offline", URL: offlineURL, Token: "t"},
	})

	reg := bonnie.NewRegistry(store, 0, discardLogger(),
		bonnie.WithRetries(1),
		bonnie.WithTimeout(200*time.Millisecond),
	)
	require.NoError(t, reg.Reload(context.Background()))

	reg.Poll(context.Background())

	updates := store.snapshotUpdates()
	require.Len(t, updates, 2)

	byID := map[string]string{}
	for _, u := range updates {
		byID[u.ID] = u.Status
	}
	assert.Equal(t, bonnie.StatusOnline, byID["online"])
	assert.Equal(t, bonnie.StatusOffline, byID["offline"])
}

func TestRegistry_Start_RunsHealthLoop(t *testing.T) {
	t.Parallel()
	srv := okServer(t)
	store := &fakeStore{}
	store.setAgents([]bonnie.Agent{{ID: "a", URL: srv.URL, Token: "t"}})

	reg := bonnie.NewRegistry(store, 20*time.Millisecond, discardLogger(),
		bonnie.WithRetries(1),
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	reg.Start(ctx)

	// Wait for multiple ticks.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if store.updCalls.Load() >= 2 {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	assert.GreaterOrEqual(t, store.updCalls.Load(), int32(2))
}

func TestRegistry_Start_ReloadError(t *testing.T) {
	t.Parallel()
	store := &fakeStore{listErr: errors.New("db down")}
	reg := bonnie.NewRegistry(store, 0, discardLogger())
	// Should not panic.
	reg.Start(context.Background())
}

func TestRegistry_HasOnlineAgent(t *testing.T) {
	t.Parallel()
	srv := okServer(t)
	store := &fakeStore{}
	store.setAgents([]bonnie.Agent{{ID: "a", URL: srv.URL, Token: "t"}})

	reg := bonnie.NewRegistry(store, 0, discardLogger(),
		bonnie.WithRetries(1),
	)
	require.NoError(t, reg.Reload(context.Background()))

	// Nothing polled yet → all agents are StatusOffline (zero value).
	require.Error(t, reg.HasOnlineAgent())

	reg.Poll(context.Background())
	require.NoError(t, reg.HasOnlineAgent())
}

func TestRegistry_HasOnlineAgent_Empty(t *testing.T) {
	t.Parallel()
	reg := bonnie.NewRegistry(&fakeStore{}, 0, discardLogger())
	require.Error(t, reg.HasOnlineAgent())
}

func TestRegistry_NilStoreReloadNoop(t *testing.T) {
	t.Parallel()
	reg := bonnie.NewRegistry(nil, 0, discardLogger())
	require.NoError(t, reg.Reload(context.Background()))
	assert.Empty(t, reg.All())
}

func TestRegistry_ConcurrentAccess(t *testing.T) {
	t.Parallel()
	reg := bonnie.NewRegistry(&fakeStore{}, 0, discardLogger())

	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		i := i
		wg.Add(1)
		go func() {
			defer wg.Done()
			id := byte('a' + i%10)
			reg.Upsert(bonnie.Agent{ID: string(id), URL: "http://x", Token: "t"})
			_, _ = reg.Get(string(id))
			_ = reg.All()
			_ = reg.Agents()
		}()
	}
	wg.Wait()
}
