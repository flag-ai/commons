package bonnie_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/flag-ai/commons/bonnie"
)

func TestRunBenchmark(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/benchmark", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodPost, r.Method)
		var spec bonnie.PairedRunSpec
		require.NoError(t, json.NewDecoder(r.Body).Decode(&spec))
		assert.Equal(t, "run-1", spec.RunID)

		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)

		writeEvent := func(ev bonnie.PairedRunEvent) {
			b, _ := json.Marshal(ev)
			_, _ = fmt.Fprintf(w, "data: %s\n\n", b)
			flusher.Flush()
		}
		writeEvent(bonnie.PairedRunEvent{Type: "status", Phase: "starting-engine"})
		writeEvent(bonnie.PairedRunEvent{Type: "progress", Source: "engine", Line: "booting"})
		writeEvent(bonnie.PairedRunEvent{
			Type: "result", Phase: "done",
			Results: json.RawMessage(`{"score":0.87}`), DurationMs: 1234,
		})
	})

	c := newClient(srv.URL)
	var events []bonnie.PairedRunEvent
	res, err := c.RunBenchmark(context.Background(), &bonnie.PairedRunSpec{
		RunID:     "run-1",
		Engine:    bonnie.EngineSpec{Image: "vllm"},
		Benchmark: bonnie.BenchmarkSpec{Image: "bench"},
	}, func(ev bonnie.PairedRunEvent) {
		events = append(events, ev)
	})
	require.NoError(t, err)
	require.NotNil(t, res)
	assert.Equal(t, int64(1234), res.DurationMs)
	assert.JSONEq(t, `{"score":0.87}`, string(res.Results))
	assert.Len(t, events, 3)
}

func TestRunBenchmark_NilCallback(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/benchmark", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		b, _ := json.Marshal(bonnie.PairedRunEvent{Type: "result", Phase: "done"})
		_, _ = fmt.Fprintf(w, "data: %s\n\n", b)
		flusher.Flush()
	})

	c := newClient(srv.URL)
	res, err := c.RunBenchmark(context.Background(), &bonnie.PairedRunSpec{
		RunID:     "x",
		Engine:    bonnie.EngineSpec{Image: "vllm"},
		Benchmark: bonnie.BenchmarkSpec{Image: "bench"},
	}, nil)
	require.NoError(t, err)
	require.NotNil(t, res)
}

func TestRunBenchmark_Error(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/benchmark", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		b, _ := json.Marshal(bonnie.PairedRunEvent{Type: "error", Phase: "engine-starting", Error: "health timeout"})
		_, _ = fmt.Fprintf(w, "data: %s\n\n", b)
		flusher.Flush()
	})

	c := newClient(srv.URL)
	_, err := c.RunBenchmark(context.Background(), &bonnie.PairedRunSpec{
		RunID:     "run-1",
		Engine:    bonnie.EngineSpec{Image: "vllm"},
		Benchmark: bonnie.BenchmarkSpec{Image: "bench"},
	}, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "health timeout")
}

func TestRunBenchmark_NoResult(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/benchmark", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		b, _ := json.Marshal(bonnie.PairedRunEvent{Type: "status", Phase: "starting"})
		_, _ = fmt.Fprintf(w, "data: %s\n\n", b)
		flusher.Flush()
	})

	c := newClient(srv.URL)
	_, err := c.RunBenchmark(context.Background(), &bonnie.PairedRunSpec{
		RunID:     "run-x",
		Engine:    bonnie.EngineSpec{Image: "vllm"},
		Benchmark: bonnie.BenchmarkSpec{Image: "bench"},
	}, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "without result")
}
