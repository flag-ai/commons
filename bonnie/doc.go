// Package bonnie provides a shared HTTP client for the BONNIE agent API.
//
// BONNIE is the on-host orchestration daemon of the FLAG platform. It exposes
// HTTP + SSE endpoints for system info, GPU status, container lifecycle,
// command execution, model storage, and paired engine/benchmark runs.
//
// This package is imported by every FLAG service that talks to BONNIE — KARR,
// KITT, and DEVON — so the wire formats, retry policy, and logging are
// consistent. Use [New] to construct a [Client], or [NewRegistry] to manage
// many agents at once with background health polling.
//
// The client applies exponential backoff with jitter on transient errors
// (network failures, 502/503/504, 429) for idempotent methods only. Non-
// idempotent methods (container creation, benchmark runs, exec) are never
// retried. Callers configure logging, HTTP timeouts, and retry count via
// functional options.
package bonnie
