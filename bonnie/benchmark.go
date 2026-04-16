package bonnie

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// EngineSpec describes the inference-engine half of a paired benchmark run.
// Mirrors BONNIE's container.EngineSpec.
type EngineSpec struct {
	Image       string            `json:"image"`
	Args        []string          `json:"args,omitempty"`
	Env         map[string]string `json:"env,omitempty"`
	Ports       []int             `json:"ports,omitempty"`
	ModelPath   string            `json:"model_path"`
	HealthCheck HealthCheck       `json:"health_check"`
}

// HealthCheck tells BONNIE how to verify the engine container is serving.
type HealthCheck struct {
	Path           string `json:"path"`
	Port           int    `json:"port"`
	TimeoutSeconds int    `json:"timeout_seconds"`
}

// BenchmarkSpec describes the benchmark half of a paired run. Mirrors
// BONNIE's container.BenchmarkSpec.
type BenchmarkSpec struct {
	Kind     string            `json:"kind"` // "yaml" or "container"
	Image    string            `json:"image"`
	Args     []string          `json:"args,omitempty"`
	Env      map[string]string `json:"env,omitempty"`
	Config   json.RawMessage   `json:"config,omitempty"`
	YAMLSpec json.RawMessage   `json:"yaml_spec,omitempty"`
}

// PairedRunSpec is the full request body for POST /api/v1/benchmark.
type PairedRunSpec struct {
	RunID          string        `json:"run_id"`
	TimeoutSeconds int           `json:"timeout_seconds"`
	Engine         EngineSpec    `json:"engine"`
	Benchmark      BenchmarkSpec `json:"benchmark"`
}

// PairedRunEvent is a single streamed event from a paired benchmark run.
// Mirrors BONNIE's container.PairedRunEvent. Type is one of "status",
// "progress", "result", or "error".
type PairedRunEvent struct {
	Type       string          `json:"type"`
	Phase      string          `json:"phase,omitempty"`
	Source     string          `json:"source,omitempty"`
	Line       string          `json:"line,omitempty"`
	Timestamp  time.Time       `json:"timestamp"`
	Results    json.RawMessage `json:"results,omitempty"`
	DurationMs int64           `json:"duration_ms,omitempty"`
	Error      string          `json:"error,omitempty"`
}

// BenchmarkResult is the terminal result emitted by RunBenchmark, extracted
// from the final {Type:"result"} SSE event.
type BenchmarkResult struct {
	Phase      string          `json:"phase,omitempty"`
	Results    json.RawMessage `json:"results,omitempty"`
	DurationMs int64           `json:"duration_ms,omitempty"`
}

// RunBenchmark streams events from POST /api/v1/benchmark. The run is
// non-idempotent — we never retry on transient failure; the caller owns
// run lifecycle.
//
// onEvent is invoked for every decoded event in order. The returned
// BenchmarkResult is extracted from the terminal {Type:"result"} event;
// a {Type:"error"} event aborts the stream with a Go error unless a
// result was already observed.
func (c *httpClient) RunBenchmark(ctx context.Context, spec *PairedRunSpec, onEvent func(PairedRunEvent)) (*BenchmarkResult, error) {
	body, err := json.Marshal(spec)
	if err != nil {
		return nil, fmt.Errorf("bonnie: marshal paired run: %w", err)
	}

	var result *BenchmarkResult
	var streamErr error
	err = c.streamSSE(ctx, http.MethodPost, "/api/v1/benchmark", body, "run benchmark",
		func(data string) error {
			var ev PairedRunEvent
			if jerr := json.Unmarshal([]byte(data), &ev); jerr != nil {
				// Malformed event — log and skip rather than terminate.
				c.opts.logger.Debug("bonnie: skipping malformed sse event",
					"op", "run benchmark", "error", jerr)
				return nil
			}
			if onEvent != nil {
				onEvent(ev)
			}
			switch ev.Type {
			case "result":
				result = &BenchmarkResult{
					Phase:      ev.Phase,
					Results:    ev.Results,
					DurationMs: ev.DurationMs,
				}
			case "error":
				streamErr = fmt.Errorf("bonnie: benchmark %s: %s", ev.Phase, ev.Error)
			}
			return nil
		})
	if err != nil {
		return nil, err
	}
	if streamErr != nil && result == nil {
		return nil, streamErr
	}
	if result == nil {
		return nil, fmt.Errorf("bonnie: benchmark stream ended without result")
	}
	return result, nil
}
