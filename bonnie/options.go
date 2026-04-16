package bonnie

import (
	"log/slog"
	"net/http"
	"time"
)

// Default client configuration. Exposed so callers can reference them in
// their own defaults.
const (
	DefaultTimeout = 30 * time.Second
	DefaultRetries = 3
)

// Option configures a Client.
type Option func(*clientOptions)

type clientOptions struct {
	httpClient *http.Client
	logger     *slog.Logger
	retries    int
	timeout    time.Duration
}

func defaultClientOptions() clientOptions {
	return clientOptions{
		retries: DefaultRetries,
		timeout: DefaultTimeout,
		logger:  slog.Default(),
	}
}

// WithHTTPClient sets a custom *http.Client for non-streaming requests.
// When set, WithTimeout is ignored — the caller is responsible for the
// client's Timeout.
func WithHTTPClient(c *http.Client) Option {
	return func(o *clientOptions) {
		o.httpClient = c
	}
}

// WithLogger sets the slog.Logger used for request tracing. Defaults to
// slog.Default().
func WithLogger(l *slog.Logger) Option {
	return func(o *clientOptions) {
		if l != nil {
			o.logger = l
		}
	}
}

// WithRetries sets the maximum number of attempts for idempotent requests.
// Value must be >= 1; values <= 0 fall back to DefaultRetries.
func WithRetries(n int) Option {
	return func(o *clientOptions) {
		if n >= 1 {
			o.retries = n
		}
	}
}

// WithTimeout sets the per-request timeout for the default HTTP client.
// Ignored when WithHTTPClient is also supplied.
func WithTimeout(d time.Duration) Option {
	return func(o *clientOptions) {
		if d > 0 {
			o.timeout = d
		}
	}
}
