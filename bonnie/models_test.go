package bonnie_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/flag-ai/commons/bonnie"
)

func TestFetchModel(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	want := bonnie.ModelEntry{
		ID: "abc", Source: "huggingface", ModelID: "Qwen/Qwen2.5-0.5B",
		Path: "/var/lib/bonnie/models/abc", SizeBytes: 1234,
		Files: []string{"config.json", "model.safetensors"},
	}
	mux.HandleFunc("/api/v1/models/fetch", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodPost, r.Method)
		var req bonnie.FetchModelRequest
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))
		assert.Equal(t, "huggingface", req.Source)
		assert.Equal(t, "Qwen/Qwen2.5-0.5B", req.ModelID)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(want)
	})

	c := newClient(srv.URL)
	got, err := c.FetchModel(context.Background(), &bonnie.FetchModelRequest{
		Source: "huggingface", ModelID: "Qwen/Qwen2.5-0.5B",
	})
	require.NoError(t, err)
	assert.Equal(t, want.ID, got.ID)
	assert.Equal(t, want.Files, got.Files)
}

func TestFetchModel_ServerError(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/models/fetch", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = io.WriteString(w, `{"error":"fetch failed"}`)
	})

	c := newClient(srv.URL)
	_, err := c.FetchModel(context.Background(), &bonnie.FetchModelRequest{
		Source: "huggingface", ModelID: "m/x",
	})
	require.Error(t, err)
	var be *bonnie.BonnieError
	require.ErrorAs(t, err, &be)
	assert.Equal(t, http.StatusInternalServerError, be.Status)
}

func TestListModels(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	want := []bonnie.ModelEntry{
		{ID: "a", Source: "huggingface", ModelID: "m/a"},
		{ID: "b", Source: "nfs", ModelID: "m/b"},
	}
	mux.HandleFunc("/api/v1/models", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodGet, r.Method)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(want)
	})

	c := newClient(srv.URL)
	got, err := c.ListModels(context.Background())
	require.NoError(t, err)
	require.Len(t, got, 2)
	assert.Equal(t, "a", got[0].ID)
}

func TestListModels_Empty(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/models", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `[]`)
	})

	c := newClient(srv.URL)
	got, err := c.ListModels(context.Background())
	require.NoError(t, err)
	assert.Empty(t, got)
}

func TestDeleteModel(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/models/abc", func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodDelete, r.Method)
		w.WriteHeader(http.StatusNoContent)
	})

	c := newClient(srv.URL)
	require.NoError(t, c.DeleteModel(context.Background(), "abc"))
}

func TestDeleteModel_NotFound(t *testing.T) {
	t.Parallel()
	srv, mux := newServer(t)
	mux.HandleFunc("/api/v1/models/missing", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})

	c := newClient(srv.URL)
	err := c.DeleteModel(context.Background(), "missing")
	require.Error(t, err)
	assert.True(t, errors.Is(err, bonnie.ErrNotFound))
}
