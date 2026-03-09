package secrets

import (
	"fmt"
	"log/slog"
	"os"
)

// ProviderType identifies a secrets backend.
type ProviderType string

const (
	ProviderEnv     ProviderType = "env"
	ProviderOpenBao ProviderType = "openbao"
)

// NewProvider creates a secrets Provider based on the given type.
// For ProviderOpenBao, OPENBAO_ADDR and OPENBAO_TOKEN environment variables must be set.
func NewProvider(providerType ProviderType, logger *slog.Logger) (Provider, error) {
	switch providerType {
	case ProviderEnv:
		return NewEnvProvider(), nil
	case ProviderOpenBao:
		addr := os.Getenv("OPENBAO_ADDR")
		if addr == "" {
			return nil, fmt.Errorf("secrets: OPENBAO_ADDR environment variable not set")
		}
		token := os.Getenv("OPENBAO_TOKEN")
		if token == "" {
			return nil, fmt.Errorf("secrets: OPENBAO_TOKEN environment variable not set")
		}
		var opts []OpenBaoOption
		if logger != nil {
			opts = append(opts, WithLogger(logger))
		}
		return NewOpenBaoProvider(addr, token, opts...), nil
	default:
		return nil, fmt.Errorf("secrets: unknown provider type %q", providerType)
	}
}
