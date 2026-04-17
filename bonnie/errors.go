package bonnie

import (
	"errors"
	"fmt"
)

// Sentinel errors returned by the client. Callers should compare with
// errors.Is rather than inspecting messages.
var (
	// ErrUnauthorized is returned when BONNIE rejects the bearer token
	// (HTTP 401 or 403).
	ErrUnauthorized = errors.New("bonnie: unauthorized")

	// ErrNotFound is returned when a resource (container, model, etc.) is
	// not present on the BONNIE host (HTTP 404).
	ErrNotFound = errors.New("bonnie: not found")

	// ErrBadRequest is returned when BONNIE rejects the request body or
	// parameters (HTTP 400).
	ErrBadRequest = errors.New("bonnie: bad request")
)

// BonnieError wraps a non-2xx HTTP response. Callers can inspect Status and
// Body for diagnostics, or use errors.Is to match one of the sentinel errors
// above (ErrUnauthorized, ErrNotFound, ErrBadRequest).
//
// The name intentionally stutters (bonnie.BonnieError) to make the type
// obvious at call sites that already import half a dozen "Error" types
// from other packages.
//
//nolint:revive // stuttering type name is deliberate, see godoc above.
type BonnieError struct {
	Op     string
	Status int
	Body   string
}

// Error implements error.
func (e *BonnieError) Error() string {
	return fmt.Sprintf("bonnie: %s returned %d: %s", e.Op, e.Status, e.Body)
}

// Is reports whether e matches the target sentinel error.
func (e *BonnieError) Is(target error) bool {
	switch target {
	case ErrUnauthorized:
		return e.Status == 401 || e.Status == 403
	case ErrNotFound:
		return e.Status == 404
	case ErrBadRequest:
		return e.Status == 400
	}
	return false
}

// newBonnieError builds a BonnieError from a non-2xx response. Body is
// truncated to maxErrBody bytes to avoid blowing up logs on oversized
// payloads.
func newBonnieError(op string, status int, body []byte) *BonnieError {
	const maxErrBody = 4096
	if len(body) > maxErrBody {
		body = body[:maxErrBody]
	}
	return &BonnieError{Op: op, Status: status, Body: string(body)}
}
