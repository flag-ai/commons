package bonnie

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Client is the operations every FLAG service uses to talk to a BONNIE
// agent. Implementations must be safe for concurrent use; the default
// implementation returned by [New] is.
type Client interface {
	// Health returns nil when the agent's /health endpoint is reachable
	// and reports a 2xx status.
	Health(ctx context.Context) error

	// SystemInfo returns host system info (OS, CPU, memory, disk).
	SystemInfo(ctx context.Context) (*SystemInfoResponse, error)

	// GPUStatus returns a point-in-time GPU snapshot.
	GPUStatus(ctx context.Context) (*GPUSnapshot, error)

	// GPUMetrics returns the Prometheus-formatted metrics payload.
	GPUMetrics(ctx context.Context) (*GPUMetrics, error)

	// ListContainers returns every container on the host.
	ListContainers(ctx context.Context) ([]ContainerInfo, error)

	// InspectContainer returns the raw Docker inspect payload for id.
	InspectContainer(ctx context.Context, id string) (*ContainerDetail, error)

	// CreateContainer creates a new container and returns its id.
	CreateContainer(ctx context.Context, req *CreateContainerRequest) (string, error)

	// StartContainer starts a created container.
	StartContainer(ctx context.Context, id string) error

	// StopContainer stops a running container.
	StopContainer(ctx context.Context, id string) error

	// RestartContainer restarts a container.
	RestartContainer(ctx context.Context, id string) error

	// RemoveContainer force-removes a container.
	RemoveContainer(ctx context.Context, id string) error

	// StreamContainerLogs streams SSE log lines and invokes onLine for
	// each. Returns when the stream closes or ctx is cancelled.
	StreamContainerLogs(ctx context.Context, id string, onLine func(string)) error

	// Exec runs a command on the host, delivering each stdout line via
	// onLine, and returns the exit code when the stream closes.
	Exec(ctx context.Context, req *ExecRequest, onLine func(string)) (*ExecResult, error)
}

// httpClient implements Client against a BONNIE HTTP server.
type httpClient struct {
	baseURL string
	token   string
	opts    clientOptions
	http    *http.Client
	rng     *rand.Rand
}

// New constructs a Client pointing at baseURL with the given bearer token.
// Use the returned value concurrently; each method is safe for parallel
// callers.
func New(baseURL, token string, opts ...Option) Client {
	o := defaultClientOptions()
	for _, opt := range opts {
		opt(&o)
	}

	hc := o.httpClient
	if hc == nil {
		hc = &http.Client{Timeout: o.timeout}
	}

	return &httpClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		token:   token,
		opts:    o,
		http:    hc,
		// Jitter is used only to spread retry backoff across clients;
		// it's not security-sensitive. Crypto randomness would be overkill.
		rng: rand.New(rand.NewSource(time.Now().UnixNano())), // #nosec G404
	}
}

// requestOptions describes a single outbound request. idempotent controls
// whether the client may retry on transient failures.
type requestOptions struct {
	method     string
	path       string
	body       []byte
	idempotent bool
	op         string // human-readable operation name, used in errors and logs
}

// do dispatches a request with retry/backoff for idempotent methods. The
// returned response body is not drained; callers must close resp.Body.
func (c *httpClient) do(ctx context.Context, req requestOptions) (*http.Response, error) {
	reqURL, err := url.JoinPath(c.baseURL, req.path)
	if err != nil {
		return nil, fmt.Errorf("bonnie: build url: %w", err)
	}

	maxAttempts := 1
	if req.idempotent {
		maxAttempts = c.opts.retries
	}

	var lastErr error
	for attempt := 0; attempt < maxAttempts; attempt++ {
		if attempt > 0 {
			c.opts.logger.Info("bonnie: retrying request",
				"op", req.op, "attempt", attempt+1, "of", maxAttempts)
		}

		var body io.Reader
		if req.body != nil {
			body = bytes.NewReader(req.body)
		}

		httpReq, err := http.NewRequestWithContext(ctx, req.method, reqURL, body)
		if err != nil {
			return nil, fmt.Errorf("bonnie: create request: %w", err)
		}
		httpReq.Header.Set("Content-Type", "application/json")
		httpReq.Header.Set("Accept", "application/json")
		if c.token != "" {
			httpReq.Header.Set("Authorization", "Bearer "+c.token)
		}

		start := time.Now()
		resp, err := c.http.Do(httpReq)
		latency := time.Since(start)

		if err != nil {
			lastErr = err
			c.opts.logger.Debug("bonnie: request error",
				"op", req.op, "method", req.method, "path", req.path,
				"attempt", attempt+1, "error", err, "latency_ms", latency.Milliseconds())
			if !req.idempotent {
				return nil, fmt.Errorf("bonnie: %s: %w", req.op, err)
			}
			if sleepErr := sleepCtx(ctx, backoffDelay(attempt, "", c.rng)); sleepErr != nil {
				return nil, sleepErr
			}
			continue
		}

		c.opts.logger.Debug("bonnie: request",
			"op", req.op, "method", req.method, "path", req.path,
			"status", resp.StatusCode, "latency_ms", latency.Milliseconds())

		if req.idempotent && retryableStatus(resp.StatusCode) && attempt+1 < maxAttempts {
			retryAfter := resp.Header.Get("Retry-After")
			body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
			_ = resp.Body.Close()
			lastErr = newBonnieError(req.op, resp.StatusCode, body)
			if sleepErr := sleepCtx(ctx, backoffDelay(attempt, retryAfter, c.rng)); sleepErr != nil {
				return nil, sleepErr
			}
			continue
		}

		return resp, nil
	}

	c.opts.logger.Warn("bonnie: request failed after retries",
		"op", req.op, "attempts", maxAttempts, "error", lastErr)
	return nil, fmt.Errorf("bonnie: %s failed after %d attempts: %w", req.op, maxAttempts, lastErr)
}

// checkStatus reads the response body and returns a typed error for
// non-2xx responses. On 2xx the body remains open for the caller.
func checkStatus(resp *http.Response, op string) error {
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	return newBonnieError(op, resp.StatusCode, body)
}

// closeBody swallows the error from resp.Body.Close. Used in defer to
// appease errcheck without noisy inline assignments.
func closeBody(resp *http.Response) {
	_ = resp.Body.Close()
}

// --- Health ---

func (c *httpClient) Health(ctx context.Context) error {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodGet, path: "/health", idempotent: true, op: "health",
	})
	if err != nil {
		return err
	}
	defer closeBody(resp)
	return checkStatus(resp, "health")
}

// --- System & GPU ---

func (c *httpClient) SystemInfo(ctx context.Context) (*SystemInfoResponse, error) {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodGet, path: "/api/v1/system/info", idempotent: true, op: "system info",
	})
	if err != nil {
		return nil, err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "system info"); err != nil {
		return nil, err
	}
	var out SystemInfoResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("bonnie: decode system info: %w", err)
	}
	return &out, nil
}

func (c *httpClient) GPUStatus(ctx context.Context) (*GPUSnapshot, error) {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodGet, path: "/api/v1/gpu/status", idempotent: true, op: "gpu status",
	})
	if err != nil {
		return nil, err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "gpu status"); err != nil {
		return nil, err
	}
	var out GPUSnapshot
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("bonnie: decode gpu status: %w", err)
	}
	return &out, nil
}

func (c *httpClient) GPUMetrics(ctx context.Context) (*GPUMetrics, error) {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodGet, path: "/api/v1/gpu/metrics", idempotent: true, op: "gpu metrics",
	})
	if err != nil {
		return nil, err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "gpu metrics"); err != nil {
		return nil, err
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("bonnie: read gpu metrics: %w", err)
	}
	return &GPUMetrics{
		ContentType: resp.Header.Get("Content-Type"),
		Body:        string(body),
	}, nil
}

// --- Containers ---

func (c *httpClient) ListContainers(ctx context.Context) ([]ContainerInfo, error) {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodGet, path: "/api/v1/containers", idempotent: true, op: "list containers",
	})
	if err != nil {
		return nil, err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "list containers"); err != nil {
		return nil, err
	}
	var out []ContainerInfo
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("bonnie: decode containers: %w", err)
	}
	return out, nil
}

func (c *httpClient) InspectContainer(ctx context.Context, id string) (*ContainerDetail, error) {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodGet, path: "/api/v1/containers/" + url.PathEscape(id),
		idempotent: true, op: "inspect container",
	})
	if err != nil {
		return nil, err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "inspect container"); err != nil {
		return nil, err
	}
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("bonnie: read inspect body: %w", err)
	}
	return &ContainerDetail{Raw: raw}, nil
}

func (c *httpClient) CreateContainer(ctx context.Context, req *CreateContainerRequest) (string, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return "", fmt.Errorf("bonnie: marshal create: %w", err)
	}
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodPost, path: "/api/v1/containers", body: body,
		idempotent: false, op: "create container",
	})
	if err != nil {
		return "", err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "create container"); err != nil {
		return "", err
	}
	var out struct {
		ID string `json:"id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", fmt.Errorf("bonnie: decode create: %w", err)
	}
	return out.ID, nil
}

func (c *httpClient) containerAction(ctx context.Context, id, action string) error {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodPost,
		path:   "/api/v1/containers/" + url.PathEscape(id) + "/" + action,
		// State transitions aren't safe to retry blindly on network
		// failure — a second start after a successful-but-cut-off request
		// might conflict. Treat as non-idempotent.
		idempotent: false,
		op:         action + " container",
	})
	if err != nil {
		return err
	}
	defer closeBody(resp)
	return checkStatus(resp, action+" container")
}

func (c *httpClient) StartContainer(ctx context.Context, id string) error {
	return c.containerAction(ctx, id, "start")
}

func (c *httpClient) StopContainer(ctx context.Context, id string) error {
	return c.containerAction(ctx, id, "stop")
}

func (c *httpClient) RestartContainer(ctx context.Context, id string) error {
	return c.containerAction(ctx, id, "restart")
}

func (c *httpClient) RemoveContainer(ctx context.Context, id string) error {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodDelete,
		path:   "/api/v1/containers/" + url.PathEscape(id),
		// DELETE is idempotent per RFC 7231.
		idempotent: true,
		op:         "remove container",
	})
	if err != nil {
		return err
	}
	defer closeBody(resp)
	return checkStatus(resp, "remove container")
}

// StreamContainerLogs runs as long as the remote stream stays open. It is
// not retried on transient failure — callers should retry at their level
// if they need reconnection.
func (c *httpClient) StreamContainerLogs(ctx context.Context, id string, onLine func(string)) error {
	return c.streamSSE(ctx, http.MethodGet,
		"/api/v1/containers/"+url.PathEscape(id)+"/logs", nil,
		"stream container logs",
		func(line string) error {
			onLine(line)
			return nil
		})
}

// --- Exec ---

func (c *httpClient) Exec(ctx context.Context, req *ExecRequest, onLine func(string)) (*ExecResult, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("bonnie: marshal exec: %w", err)
	}

	// BONNIE's exec handler emits one or more "data: <payload>" frames then
	// an "event: done\ndata: {\"exit_code\": N}" frame. We call onLine for
	// payloads that parse as error-free strings and return ExecResult when
	// we see the done event or the stream closes.
	var result ExecResult
	err = c.streamSSEExec(ctx, http.MethodPost, "/api/v1/exec", body, "exec",
		func(event, data string) error {
			if event == "done" {
				var done struct {
					ExitCode int    `json:"exit_code"`
					Error    string `json:"error,omitempty"`
				}
				if jerr := json.Unmarshal([]byte(data), &done); jerr == nil {
					result.ExitCode = done.ExitCode
					if done.Error != "" {
						return fmt.Errorf("bonnie: exec: %s", done.Error)
					}
				}
				return nil
			}
			// Default event: inspect for an error envelope, otherwise pass
			// through as a log line.
			var errEnvelope struct {
				Error string `json:"error,omitempty"`
			}
			if jerr := json.Unmarshal([]byte(data), &errEnvelope); jerr == nil && errEnvelope.Error != "" {
				return fmt.Errorf("bonnie: exec: %s", errEnvelope.Error)
			}
			onLine(data)
			return nil
		})
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// --- SSE helpers ---

// streamSSE dispatches an SSE request and calls onData for each decoded
// data frame. event lines are folded into the data payload format used by
// BONNIE's container log handler (which only emits data: frames).
//
// A separate streaming HTTP client is used so idle reads don't trip the
// non-streaming client's Timeout. Canceling ctx terminates the stream.
func (c *httpClient) streamSSE(ctx context.Context, method, path string, body []byte, op string,
	onData func(string) error,
) error {
	return c.streamSSEExec(ctx, method, path, body, op, func(_, data string) error {
		return onData(data)
	})
}

// streamSSEExec is the shared implementation behind streamSSE and Exec's
// SSE loop. onFrame receives (event, data) — event defaults to "" unless
// the server explicitly sent an event: line.
func (c *httpClient) streamSSEExec(ctx context.Context, method, path string, body []byte, op string,
	onFrame func(event, data string) error,
) error {
	reqURL, err := url.JoinPath(c.baseURL, path)
	if err != nil {
		return fmt.Errorf("bonnie: build url: %w", err)
	}

	var reqBody io.Reader
	if body != nil {
		reqBody = bytes.NewReader(body)
	}

	req, err := http.NewRequestWithContext(ctx, method, reqURL, reqBody)
	if err != nil {
		return fmt.Errorf("bonnie: create stream request: %w", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "text/event-stream")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}

	// Streaming requires an HTTP client without the default per-request
	// Timeout — a long-running stream would otherwise be killed. We reuse
	// the user-supplied client's Transport so dialers, proxies, and TLS
	// config are respected.
	streamClient := &http.Client{Transport: c.http.Transport}

	start := time.Now()
	resp, err := streamClient.Do(req)
	if err != nil {
		return fmt.Errorf("bonnie: %s: %w", op, err)
	}
	defer closeBody(resp)

	if err := checkStatus(resp, op); err != nil {
		c.opts.logger.Debug("bonnie: stream error status",
			"op", op, "status", resp.StatusCode, "latency_ms", time.Since(start).Milliseconds())
		return err
	}
	c.opts.logger.Debug("bonnie: stream open",
		"op", op, "latency_ms", time.Since(start).Milliseconds())

	return parseSSE(ctx, resp.Body, onFrame)
}

// Compile-time assertion that httpClient satisfies Client.
var _ Client = (*httpClient)(nil)
