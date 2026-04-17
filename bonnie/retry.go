package bonnie

import (
	"context"
	"math/rand"
	"net/http"
	"strconv"
	"time"
)

// retryBaseDelay is the first-attempt backoff. Subsequent attempts double
// this up to retryMaxDelay; each delay has ±25% jitter applied.
const (
	retryBaseDelay = 100 * time.Millisecond
	retryMaxDelay  = 5 * time.Second
	retryJitter    = 0.25
)

// retryableStatus reports whether an HTTP status code is eligible for
// automatic retry. Transient upstream failures (5xx except 501, plus 429
// rate-limiting) retry; everything else — including 4xx client errors — is
// returned to the caller immediately.
func retryableStatus(status int) bool {
	switch status {
	case http.StatusBadGateway,
		http.StatusServiceUnavailable,
		http.StatusGatewayTimeout,
		http.StatusTooManyRequests:
		return true
	}
	return false
}

// backoffDelay returns the wait duration before retry attempt number
// (0-indexed). If the server sent a Retry-After header we honour it;
// otherwise we use exponential backoff with jitter.
func backoffDelay(attempt int, retryAfter string) time.Duration {
	if retryAfter != "" {
		if secs, err := strconv.Atoi(retryAfter); err == nil && secs > 0 {
			return time.Duration(secs) * time.Second
		}
	}

	// #nosec G115 -- attempt is bounded by retries (default 3); shift is safe.
	shift := uint(attempt)
	base := retryBaseDelay << shift
	if base > retryMaxDelay || base <= 0 {
		base = retryMaxDelay
	}

	// Apply ±retryJitter jitter.
	// The global rand source is goroutine-safe (since Go 1.0) and
	// automatically seeded (since Go 1.20). No per-client *rand.Rand needed.
	jitter := (rand.Float64()*2 - 1) * retryJitter // #nosec G404 -- jitter for backoff, not security
	delay := time.Duration(float64(base) * (1 + jitter))
	if delay < 0 {
		delay = 0
	}
	return delay
}

// sleepCtx waits for d or until ctx is done, whichever comes first.
func sleepCtx(ctx context.Context, d time.Duration) error {
	if d <= 0 {
		return ctx.Err()
	}
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
