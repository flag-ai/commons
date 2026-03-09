package health

import (
	"context"
	"sync"
	"time"
)

// Registry holds a set of health checkers and runs them concurrently.
type Registry struct {
	mu       sync.RWMutex
	checkers []Checker
}

// NewRegistry creates an empty health check registry.
func NewRegistry() *Registry {
	return &Registry{}
}

// Register adds a checker to the registry.
func (r *Registry) Register(c Checker) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.checkers = append(r.checkers, c)
}

// RunAll executes all registered checks concurrently and returns a Report.
func (r *Registry) RunAll(ctx context.Context) *Report {
	r.mu.RLock()
	checkers := make([]Checker, len(r.checkers))
	copy(checkers, r.checkers)
	r.mu.RUnlock()

	report := NewReport()
	if len(checkers) == 0 {
		return report
	}

	results := make([]Status, len(checkers))
	var wg sync.WaitGroup

	for i, c := range checkers {
		wg.Add(1)
		go func(idx int, checker Checker) {
			defer wg.Done()

			start := time.Now()
			err := checker.Check(ctx)
			latency := time.Since(start)

			s := Status{
				Name:    checker.Name(),
				Healthy: err == nil,
				Latency: latency,
			}
			if err != nil {
				s.Error = err.Error()
			}
			results[idx] = s
		}(i, c)
	}

	wg.Wait()

	for _, s := range results {
		report.Checks = append(report.Checks, s)
		if !s.Healthy {
			report.Healthy = false
		}
	}

	return report
}
