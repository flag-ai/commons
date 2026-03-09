// Package secrets provides a unified interface for retrieving secrets from
// various backends (environment variables, OpenBao, etc.).
package secrets

import "context"

// Provider retrieves secret values by key.
type Provider interface {
	// Get retrieves a secret value. Returns an error if the key is not found.
	Get(ctx context.Context, key string) (string, error)

	// GetOrDefault retrieves a secret value, returning defaultVal if not found.
	GetOrDefault(ctx context.Context, key, defaultVal string) string
}
