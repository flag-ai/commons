package bonnie

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

// Agent is the minimal agent record held in the registry. Callers
// persist richer rows in their own DB; this is the shared shape that
// flows through RegistryStore.
type Agent struct {
	ID         string
	Name       string
	URL        string
	Token      string
	Status     string
	LastSeenAt time.Time
}

// RegistryStore abstracts persistent storage of agents. KARR, KITT, and
// DEVON each implement this against their own sqlc-generated queries —
// the package does not know or care about their schemas.
type RegistryStore interface {
	// List returns every agent known to the store.
	List(ctx context.Context) ([]Agent, error)
	// UpdateStatus marks an agent online/offline with the timestamp of
	// the most recent health check.
	UpdateStatus(ctx context.Context, id, status string, lastSeenAt time.Time) error
}

// Status tags recorded by the registry health loop.
const (
	StatusOnline  = "online"
	StatusOffline = "offline"
)

// entry pairs an Agent with its live Client.
type entry struct {
	agent  Agent
	client Client
}

// Registry manages a set of BONNIE clients, one per registered agent,
// and polls them for health in a background goroutine.
type Registry struct {
	store        RegistryStore
	pollInterval time.Duration
	logger       *slog.Logger
	clientOpts   []Option

	mu      sync.RWMutex
	entries map[string]*entry
}

// NewRegistry constructs a Registry that reads agents from store and
// polls them every pollInterval. clientOpts are forwarded to every
// constructed Client so callers can share HTTP clients, loggers, retry
// counts, etc.
//
// pollInterval <= 0 disables automatic polling; callers can still invoke
// Reload and Poll explicitly.
func NewRegistry(store RegistryStore, pollInterval time.Duration, logger *slog.Logger, clientOpts ...Option) *Registry {
	if logger == nil {
		logger = slog.Default()
	}
	return &Registry{
		store:        store,
		pollInterval: pollInterval,
		logger:       logger,
		clientOpts:   clientOpts,
		entries:      map[string]*entry{},
	}
}

// Start kicks off the background health loop. It first reloads from the
// store, then polls on the configured interval until ctx is cancelled.
// It is safe to call Start more than once — subsequent calls each spawn
// a goroutine, so callers typically invoke it exactly once during
// service bootstrap.
func (r *Registry) Start(ctx context.Context) {
	if err := r.Reload(ctx); err != nil {
		r.logger.Warn("bonnie: registry initial reload failed", "error", err)
	}
	if r.pollInterval <= 0 {
		return
	}
	go r.loop(ctx)
}

func (r *Registry) loop(ctx context.Context) {
	t := time.NewTicker(r.pollInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			r.Poll(ctx)
		}
	}
}

// Reload replaces the in-memory set of agents with the rows currently in
// the store. Existing Client instances are reused when URL and Token
// haven't changed.
func (r *Registry) Reload(ctx context.Context) error {
	if r.store == nil {
		return nil
	}
	agents, err := r.store.List(ctx)
	if err != nil {
		return err
	}

	next := make(map[string]*entry, len(agents))

	r.mu.RLock()
	for i := range agents {
		a := agents[i]
		if existing, ok := r.entries[a.ID]; ok && existing.agent.URL == a.URL && existing.agent.Token == a.Token {
			next[a.ID] = &entry{agent: a, client: existing.client}
			continue
		}
		next[a.ID] = &entry{
			agent:  a,
			client: New(a.URL, a.Token, r.clientOpts...),
		}
	}
	r.mu.RUnlock()

	r.mu.Lock()
	r.entries = next
	r.mu.Unlock()

	r.logger.Debug("bonnie: registry reloaded", "count", len(next))
	return nil
}

// Upsert registers (or replaces) a single agent without touching the
// rest of the registry. Used when a service persists a newly registered
// agent and wants it available immediately, without waiting for the
// next poll.
func (r *Registry) Upsert(a Agent) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.entries[a.ID] = &entry{
		agent:  a,
		client: New(a.URL, a.Token, r.clientOpts...),
	}
}

// Remove unregisters an agent by id. Unknown ids are silently ignored.
func (r *Registry) Remove(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.entries, id)
}

// Get returns the Client registered for id. The second return value is
// false when no agent with that id is known.
func (r *Registry) Get(id string) (Client, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	e, ok := r.entries[id]
	if !ok {
		return nil, false
	}
	return e.client, true
}

// All returns a snapshot of every registered Client keyed by agent id.
// The returned map is a copy — mutating it has no effect on the
// registry.
func (r *Registry) All() map[string]Client {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make(map[string]Client, len(r.entries))
	for id, e := range r.entries {
		out[id] = e.client
	}
	return out
}

// Agents returns a snapshot of every registered Agent record.
func (r *Registry) Agents() []Agent {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]Agent, 0, len(r.entries))
	for _, e := range r.entries {
		out = append(out, e.agent)
	}
	return out
}

// Poll runs Health against every registered agent and persists the
// result via RegistryStore.UpdateStatus. Called on each tick of the
// background loop; exposed for tests and for callers that want to
// trigger a refresh on demand.
func (r *Registry) Poll(ctx context.Context) {
	r.mu.RLock()
	snap := make([]*entry, 0, len(r.entries))
	for _, e := range r.entries {
		snap = append(snap, e)
	}
	r.mu.RUnlock()

	for _, e := range snap {
		status := StatusOnline
		if err := e.client.Health(ctx); err != nil {
			status = StatusOffline
			r.logger.Debug("bonnie: registry health check failed",
				"agent", e.agent.Name, "id", e.agent.ID, "error", err)
		}

		now := time.Now().UTC()
		if r.store != nil {
			if err := r.store.UpdateStatus(ctx, e.agent.ID, status, now); err != nil {
				r.logger.Error("bonnie: registry update status failed",
					"agent", e.agent.Name, "id", e.agent.ID, "error", err)
			}
		}

		r.mu.Lock()
		if cur, ok := r.entries[e.agent.ID]; ok {
			cur.agent.Status = status
			cur.agent.LastSeenAt = now
		}
		r.mu.Unlock()
	}
}

// HasOnlineAgent returns nil when at least one registered agent is
// marked online. Useful as a /health sub-check for services that
// require at least one reachable BONNIE host.
func (r *Registry) HasOnlineAgent() error {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if len(r.entries) == 0 {
		return errNoAgentsRegistered
	}
	for _, e := range r.entries {
		if e.agent.Status == StatusOnline {
			return nil
		}
	}
	return errNoOnlineAgents
}
