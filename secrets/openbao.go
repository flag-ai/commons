package secrets

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"sync"
	"time"
)

// OpenBaoProvider retrieves secrets from an OpenBao (Vault-compatible) server.
// It caches secrets in memory and supports token-based authentication.
type OpenBaoProvider struct {
	addr   string
	token  string
	mount  string
	client *http.Client
	logger *slog.Logger

	mu    sync.RWMutex
	cache map[string]cacheEntry
}

type cacheEntry struct {
	value   string
	expires time.Time
}

// OpenBaoOption configures an OpenBaoProvider.
type OpenBaoOption func(*OpenBaoProvider)

// WithLogger sets the logger for the OpenBao provider.
func WithLogger(logger *slog.Logger) OpenBaoOption {
	return func(p *OpenBaoProvider) {
		p.logger = logger
	}
}

// WithHTTPClient sets a custom HTTP client for the OpenBao provider.
func WithHTTPClient(client *http.Client) OpenBaoOption {
	return func(p *OpenBaoProvider) {
		p.client = client
	}
}

// WithMount sets the secrets engine mount path (default: "kv").
func WithMount(mount string) OpenBaoOption {
	return func(p *OpenBaoProvider) {
		p.mount = mount
	}
}

// NewOpenBaoProvider creates a new OpenBaoProvider.
// addr is the OpenBao server address (e.g., "http://localhost:8200").
// token is the authentication token.
func NewOpenBaoProvider(addr, token string, opts ...OpenBaoOption) *OpenBaoProvider {
	p := &OpenBaoProvider{
		addr:   addr,
		token:  token,
		mount:  "kv",
		client: &http.Client{Timeout: 10 * time.Second},
		logger: slog.Default(),
		cache:  make(map[string]cacheEntry),
	}
	for _, opt := range opts {
		opt(p)
	}
	return p
}

// kvV2Response represents the OpenBao KV v2 secret response.
type kvV2Response struct {
	Data struct {
		Data map[string]interface{} `json:"data"`
	} `json:"data"`
}

// Get retrieves a secret from OpenBao. The key format is "path#field" where
// path is the secret path and field is the key within the secret data.
// If no field is specified, the "value" field is used.
func (p *OpenBaoProvider) Get(ctx context.Context, key string) (string, error) {
	path, field := parseKey(key)

	// Check cache
	if val, ok := p.fromCache(key); ok {
		return val, nil
	}

	val, err := p.fetchSecret(ctx, path, field)
	if err != nil {
		return "", err
	}

	p.toCache(key, val, 5*time.Minute)
	return val, nil
}

// GetOrDefault retrieves a secret from OpenBao, returning defaultVal on error.
func (p *OpenBaoProvider) GetOrDefault(ctx context.Context, key, defaultVal string) string {
	val, err := p.Get(ctx, key)
	if err != nil {
		p.logger.Debug("openbao secret fallback to default", "key", key, "error", err)
		return defaultVal
	}
	return val
}

func (p *OpenBaoProvider) fetchSecret(ctx context.Context, path, field string) (string, error) {
	url := fmt.Sprintf("%s/v1/%s/data/%s", p.addr, p.mount, path)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", fmt.Errorf("secrets: failed to create request: %w", err)
	}
	req.Header.Set("X-Vault-Token", p.token)

	resp, err := p.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("secrets: openbao request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("secrets: openbao returned %d: %s", resp.StatusCode, body)
	}

	var result kvV2Response
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("secrets: failed to decode openbao response: %w", err)
	}

	val, ok := result.Data.Data[field]
	if !ok {
		return "", fmt.Errorf("secrets: field %q not found in secret %q", field, path)
	}

	strVal, ok := val.(string)
	if !ok {
		return "", fmt.Errorf("secrets: field %q in secret %q is not a string", field, path)
	}

	return strVal, nil
}

func (p *OpenBaoProvider) fromCache(key string) (string, bool) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	entry, ok := p.cache[key]
	if !ok || time.Now().After(entry.expires) {
		return "", false
	}
	return entry.value, true
}

func (p *OpenBaoProvider) toCache(key, value string, ttl time.Duration) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cache[key] = cacheEntry{value: value, expires: time.Now().Add(ttl)}
}

// parseKey splits "path#field" into path and field. If no "#" is present,
// the field defaults to "value".
func parseKey(key string) (string, string) {
	for i := range key {
		if key[i] == '#' {
			return key[:i], key[i+1:]
		}
	}
	return key, "value"
}
