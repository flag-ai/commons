package bonnie_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/flag-ai/commons/bonnie"
)

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, &slog.HandlerOptions{Level: slog.LevelError}))
}

func newServer(t *testing.T) (*httptest.Server, *http.ServeMux) {
	t.Helper()
	mux := http.NewServeMux()
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv, mux
}

func newClient(srvURL string) bonnie.Client {
	return bonnie.New(srvURL, "test-token",
		bonnie.WithLogger(discardLogger()),
		bonnie.WithRetries(3),
	)
}

func TestNew_TrimsTrailingSlash(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	c := bonnie.New(srv.URL+"/", "tok", bonnie.WithLogger(discardLogger()))
	require.NoError(t, c.Health(context.Background()))
}

func TestHealth_OK(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "Bearer test-token", r.Header.Get("Authorization"))
		w.WriteHeader(http.StatusOK)
	})

	c := newClient(srv.URL)
	require.NoError(t, c.Health(context.Background()))
}

func TestHealth_Unauthorized(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = io.WriteString(w, `{"error":"bad token"}`)
	})

	c := newClient(srv.URL)
	err := c.Health(context.Background())
	require.Error(t, err)
	assert.True(t, errors.Is(err, bonnie.ErrUnauthorized), "expected ErrUnauthorized, got %v", err)
}

func TestHealth_NotFound(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})

	c := newClient(srv.URL)
	err := c.Health(context.Background())
	require.Error(t, err)
	assert.True(t, errors.Is(err, bonnie.ErrNotFound))
}

func TestHealth_BadRequest(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
	})

	c := newClient(srv.URL)
	err := c.Health(context.Background())
	require.Error(t, err)
	assert.True(t, errors.Is(err, bonnie.ErrBadRequest))
}

func TestSystemInfo(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	want := bonnie.SystemInfoResponse{
		System: bonnie.SystemInfo{
			Hostname: "gpu-node-1", OS: "linux", Arch: "amd64",
			Kernel: "6.1.0", CPUModel: "AMD EPYC 7763", CPUCores: 64,
			MemoryMB: 131072,
		},
		Disk: bonnie.DiskUsage{TotalGB: 1000, UsedGB: 400, AvailableGB: 600, UsedPercent: "40%"},
	}
	mux.HandleFunc("/api/v1/system/info", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodGet, r.Method)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(want)
	})

	c := newClient(srv.URL)
	got, err := c.SystemInfo(context.Background())
	require.NoError(t, err)
	assert.Equal(t, want.System.Hostname, got.System.Hostname)
	assert.Equal(t, want.System.CPUCores, got.System.CPUCores)
	assert.Equal(t, want.Disk.TotalGB, got.Disk.TotalGB)
}

func TestGPUStatus(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	ts := time.Now().UTC().Truncate(time.Second)
	want := bonnie.GPUSnapshot{
		Vendor: bonnie.GPUVendorNVIDIA,
		GPUs: []bonnie.GPUInfo{{
			Index: 0, Name: "RTX 4090", Vendor: bonnie.GPUVendorNVIDIA,
			MemoryTotal: 24576, MemoryFree: 20000, Utilization: 15,
		}},
		Timestamp: ts,
	}
	mux.HandleFunc("/api/v1/gpu/status", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(want)
	})

	c := newClient(srv.URL)
	got, err := c.GPUStatus(context.Background())
	require.NoError(t, err)
	require.Len(t, got.GPUs, 1)
	assert.Equal(t, "RTX 4090", got.GPUs[0].Name)
	assert.Equal(t, uint64(24576), got.GPUs[0].MemoryTotal)
}

func TestGPUMetrics(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/gpu/metrics", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		_, _ = io.WriteString(w, "# HELP bonnie_gpu_count ...\nbonnie_gpu_count{vendor=\"nvidia\"} 1\n")
	})

	c := newClient(srv.URL)
	got, err := c.GPUMetrics(context.Background())
	require.NoError(t, err)
	assert.Contains(t, got.Body, "bonnie_gpu_count")
	assert.Contains(t, got.ContentType, "text/plain")
}

func TestListContainers(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	want := []bonnie.ContainerInfo{
		{ID: "abc", Name: "ollama", Image: "ollama:latest", State: "running", Status: "Up", Created: 1},
		{ID: "def", Name: "vllm", Image: "vllm:latest", State: "exited", Status: "Exited", Created: 2},
	}
	mux.HandleFunc("/api/v1/containers", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodGet, r.Method)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(want)
	})

	c := newClient(srv.URL)
	got, err := c.ListContainers(context.Background())
	require.NoError(t, err)
	require.Len(t, got, 2)
	assert.Equal(t, "abc", got[0].ID)
	assert.Equal(t, "exited", got[1].State)
}

func TestInspectContainer(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/containers/abc", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"Id":"abc","State":{"Status":"running"}}`)
	})

	c := newClient(srv.URL)
	got, err := c.InspectContainer(context.Background(), "abc")
	require.NoError(t, err)
	assert.JSONEq(t, `{"Id":"abc","State":{"Status":"running"}}`, string(got.Raw))
}

func TestCreateContainer(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/containers", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodPost, r.Method)
		var req bonnie.CreateContainerRequest
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))
		assert.Equal(t, "test-container", req.Name)
		assert.True(t, req.GPU)
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(map[string]string{"id": "new-id"})
	})

	c := newClient(srv.URL)
	id, err := c.CreateContainer(context.Background(), &bonnie.CreateContainerRequest{
		Name: "test-container", Image: "ubuntu:latest", GPU: true,
	})
	require.NoError(t, err)
	assert.Equal(t, "new-id", id)
}

func TestContainerActions(t *testing.T) {
	t.Parallel()
	for _, action := range []string{"start", "stop", "restart"} {
		action := action
		t.Run(action, func(t *testing.T) {
			t.Parallel()
			srv, mux := newServer(t)
			mux.HandleFunc("/api/v1/containers/abc/"+action, func(w http.ResponseWriter, r *http.Request) {
				assert.Equal(t, http.MethodPost, r.Method)
				w.WriteHeader(http.StatusOK)
			})

			c := newClient(srv.URL)
			var err error
			switch action {
			case "start":
				err = c.StartContainer(context.Background(), "abc")
			case "stop":
				err = c.StopContainer(context.Background(), "abc")
			case "restart":
				err = c.RestartContainer(context.Background(), "abc")
			}
			require.NoError(t, err)
		})
	}
}

func TestRemoveContainer(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/containers/abc", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodDelete, r.Method)
		w.WriteHeader(http.StatusNoContent)
	})

	c := newClient(srv.URL)
	require.NoError(t, c.RemoveContainer(context.Background(), "abc"))
}

func TestStreamContainerLogs(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/containers/abc/logs", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "text/event-stream", r.Header.Get("Accept"))
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		for i := 0; i < 3; i++ {
			_, _ = fmt.Fprintf(w, "data: log line %d\n\n", i)
			flusher.Flush()
		}
	})

	c := newClient(srv.URL)
	var lines []string
	require.NoError(t, c.StreamContainerLogs(context.Background(), "abc", func(line string) {
		lines = append(lines, line)
	}))
	require.Len(t, lines, 3)
	assert.Equal(t, "log line 0", lines[0])
	assert.Equal(t, "log line 2", lines[2])
}

func TestExec(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/exec", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodPost, r.Method)
		var req bonnie.ExecRequest
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))
		assert.Equal(t, "ls", req.Command)
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		_, _ = io.WriteString(w, "data: file1\n\n")
		flusher.Flush()
		_, _ = io.WriteString(w, "data: file2\n\n")
		flusher.Flush()
		_, _ = io.WriteString(w, "event: done\ndata: {\"exit_code\": 0}\n\n")
		flusher.Flush()
	})

	c := newClient(srv.URL)
	var lines []string
	res, err := c.Exec(context.Background(), &bonnie.ExecRequest{Command: "ls"}, func(line string) {
		lines = append(lines, line)
	})
	require.NoError(t, err)
	require.NotNil(t, res)
	assert.Equal(t, 0, res.ExitCode)
	assert.Equal(t, []string{"file1", "file2"}, lines)
}

func TestExec_ErrorEnvelope(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/exec", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		_, _ = io.WriteString(w, "data: {\"error\": \"boom\"}\n\n")
		flusher.Flush()
	})

	c := newClient(srv.URL)
	_, err := c.Exec(context.Background(), &bonnie.ExecRequest{Command: "fail"}, func(string) {})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "boom")
}

func TestRetry_503ThenSuccess(t *testing.T) {
	t.Parallel()
	var attempts int32
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		n := atomic.AddInt32(&attempts, 1)
		if n < 3 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	})

	c := newClient(srv.URL)
	require.NoError(t, c.Health(context.Background()))
	assert.Equal(t, int32(3), atomic.LoadInt32(&attempts))
}

func TestRetry_RetryAfter(t *testing.T) {
	t.Parallel()
	var attempts int32
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		if atomic.AddInt32(&attempts, 1) < 2 {
			w.Header().Set("Retry-After", "0")
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		w.WriteHeader(http.StatusOK)
	})

	start := time.Now()
	c := newClient(srv.URL)
	require.NoError(t, c.Health(context.Background()))
	// Retry-After=0 means sleep 0s; assert we didn't stall on the backoff.
	assert.Less(t, time.Since(start), time.Second)
}

func TestRetry_NonIdempotentNotRetried(t *testing.T) {
	t.Parallel()
	var attempts int32
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/containers", func(w http.ResponseWriter, _ *http.Request) {
		atomic.AddInt32(&attempts, 1)
		w.WriteHeader(http.StatusServiceUnavailable)
	})

	c := newClient(srv.URL)
	_, err := c.CreateContainer(context.Background(), &bonnie.CreateContainerRequest{
		Name: "x", Image: "x",
	})
	require.Error(t, err)
	assert.Equal(t, int32(1), atomic.LoadInt32(&attempts),
		"CreateContainer must not retry on 503")
}

func TestRetry_4xxNotRetried(t *testing.T) {
	t.Parallel()
	var attempts int32
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		atomic.AddInt32(&attempts, 1)
		w.WriteHeader(http.StatusUnauthorized)
	})

	c := newClient(srv.URL)
	err := c.Health(context.Background())
	require.Error(t, err)
	assert.True(t, errors.Is(err, bonnie.ErrUnauthorized))
	assert.Equal(t, int32(1), atomic.LoadInt32(&attempts),
		"401 must not retry")
}

func TestContextCancellation(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(_ http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	})

	c := newClient(srv.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	err := c.Health(ctx)
	require.Error(t, err)
}

func TestBonnieError_Fields(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTeapot)
		_, _ = io.WriteString(w, "I'm a teapot")
	})

	c := newClient(srv.URL)
	err := c.Health(context.Background())
	require.Error(t, err)
	var be *bonnie.BonnieError
	require.ErrorAs(t, err, &be)
	assert.Equal(t, http.StatusTeapot, be.Status)
	assert.Contains(t, be.Body, "teapot")
}

func TestWithHTTPClient(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	custom := &http.Client{Timeout: 2 * time.Second}
	c := bonnie.New(srv.URL, "tok",
		bonnie.WithHTTPClient(custom),
		bonnie.WithLogger(discardLogger()),
	)
	require.NoError(t, c.Health(context.Background()))
}

// Verify the client doesn't blow up on comment lines or leading-space
// data: values, both of which the SSE spec allows.
func TestStreamSSE_CommentAndSpacedData(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/containers/x/logs", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)
		frames := []string{
			": heartbeat\n",
			"data: line-1\n\n",
			"data:line-2\n\n", // no space after colon
			": another comment\n",
			"data: line-3\n\n",
		}
		_, _ = io.WriteString(w, strings.Join(frames, ""))
		flusher.Flush()
	})

	c := newClient(srv.URL)
	var lines []string
	require.NoError(t, c.StreamContainerLogs(context.Background(), "x", func(l string) {
		lines = append(lines, l)
	}))
	assert.Equal(t, []string{"line-1", "line-2", "line-3"}, lines)
}
