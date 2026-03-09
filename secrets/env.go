package secrets

import (
	"context"
	"fmt"
	"os"
)

// EnvProvider retrieves secrets from environment variables.
type EnvProvider struct{}

// NewEnvProvider creates a new EnvProvider.
func NewEnvProvider() *EnvProvider {
	return &EnvProvider{}
}

// Get retrieves a secret from the environment. Returns an error if the variable is not set.
func (p *EnvProvider) Get(_ context.Context, key string) (string, error) {
	val, ok := os.LookupEnv(key)
	if !ok {
		return "", fmt.Errorf("secrets: environment variable %q not set", key)
	}
	return val, nil
}

// GetOrDefault retrieves a secret from the environment, returning defaultVal if not set.
func (p *EnvProvider) GetOrDefault(_ context.Context, key, defaultVal string) string {
	if val, ok := os.LookupEnv(key); ok {
		return val
	}
	return defaultVal
}
