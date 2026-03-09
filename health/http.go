package health

import (
	"context"
	"fmt"
	"net/http"
	"time"
)

// HTTPChecker checks the health of an HTTP endpoint.
type HTTPChecker struct {
	name   string
	url    string
	client *http.Client
}

// NewHTTPChecker creates a health checker that GETs the given URL and expects a 2xx response.
func NewHTTPChecker(name, url string) *HTTPChecker {
	return &HTTPChecker{
		name:   name,
		url:    url,
		client: &http.Client{Timeout: 5 * time.Second},
	}
}

// Name returns the checker's name.
func (c *HTTPChecker) Name() string {
	return c.name
}

// Check performs an HTTP GET and returns an error if the response is not 2xx.
func (c *HTTPChecker) Check(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.url, nil)
	if err != nil {
		return fmt.Errorf("health: failed to create request: %w", err)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return fmt.Errorf("health: request to %s failed: %w", c.name, err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("health: %s returned status %d", c.name, resp.StatusCode)
	}

	return nil
}
