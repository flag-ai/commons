// Package health provides health check infrastructure for FLAG components.
package health

import (
	"context"

	"github.com/flag-ai/commons/version"
)

// Checker performs a health check for a single dependency.
type Checker interface {
	// Name returns the name of the dependency being checked.
	Name() string

	// Check performs the health check. Returns nil if healthy.
	Check(ctx context.Context) error
}

// Status represents the result of a single health check.
type Status struct {
	Name      string `json:"name"`
	Healthy   bool   `json:"healthy"`
	Error     string `json:"error,omitempty"`
	LatencyMs int64  `json:"latency_ms"`
}

// Report is the aggregate health check response.
type Report struct {
	Healthy bool     `json:"healthy"`
	Version string   `json:"version"`
	Checks  []Status `json:"checks"`
}

// NewReport creates a Report with version info pre-populated.
func NewReport() *Report {
	return &Report{
		Healthy: true,
		Version: version.Info(),
		Checks:  []Status{},
	}
}
