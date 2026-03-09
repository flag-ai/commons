package secrets

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"sync"
	"time"
)

const (
	defaultCacheTTL    = 5 * time.Minute
	maxErrorBodyBytes  = 4096
	defaultMount       = "kv"
	defaultHTTPTimeout = 10 * time.Second
)

// OpenBaoProvider retrieves secrets from an OpenBao (Vault-compatible) server.
// It caches secrets in memory and supports token-based authentication.
type OpenBaoProvider struct {
	addr     string
	token    string
	mount    string
	cacheTTL time.Duration
	client   *http.Client
	logger   *slog.Logger

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

// WithCacheTTL sets the cache time-to-live for secrets (default: 5m).
// Set to 0 to disable caching.
func WithCacheTTL(ttl time.Duration) OpenBaoOption {
	return func(p *OpenBaoProvider) {
		p.cacheTTL = ttl
	}
}

// NewOpenBaoProvider creates a new OpenBaoProvider.
// addr is the OpenBao server address (e.g., "http://localhost:8200").
// token is the authentication token.
func NewOpenBaoProvider(addr, token string, opts ...OpenBaoOption) *OpenBaoProvider {
	p := &OpenBaoProvider{
		addr:     addr,
		token:    token,
		mount:    defaultMount,
		cacheTTL: defaultCacheTTL,
		client:   &http.Client{Timeout: defaultHTTPTimeout},
		logger:   slog.Default(),
		cache:    make(map[string]cacheEntry),
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
	path, field, err := parseKey(key)
	if err != nil {
		return "", err
	}

	// Check cache
	if val, ok := p.fromCache(key); ok {
		return val, nil
	}

	val, err := p.fetchSecret(ctx, path, field)
	if err != nil {
		return "", err
	}

	if p.cacheTTL > 0 {
		p.toCache(key, val, p.cacheTTL)
	}
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
	reqURL := fmt.Sprintf("%s/v1/%s/data/%s", p.addr, p.mount, url.PathEscape(path))

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		return "", fmt.Errorf("secrets: failed to create request: %w", err)
	}
	req.Header.Set("X-Vault-Token", p.token)

	resp, err := p.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("secrets: openbao request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, maxErrorBodyBytes))
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
	p.mu.Lock()
	defer p.mu.Unlock()
	entry, ok := p.cache[key]
	if !ok {
		return "", false
	}
	if time.Now().After(entry.expires) {
		delete(p.cache, key)
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
// the field defaults to "value". Returns an error if path or field is empty.
func parseKey(key string) (string, string, error) {
	for i := range key {
		if key[i] == '#' {
			path, field := key[:i], key[i+1:]
			if path == "" {
				return "", "", fmt.Errorf("secrets: empty path in key %q", key)
			}
			if field == "" {
				return "", "", fmt.Errorf("secrets: empty field in key %q", key)
			}
			return path, field, nil
		}
	}
	if key == "" {
		return "", "", fmt.Errorf("secrets: empty key")
	}
	return key, "value", nil
}
