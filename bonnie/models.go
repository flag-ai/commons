package bonnie

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

// FetchModelRequest is the request body for POST /api/v1/models/fetch. Field
// tags mirror BONNIE's storage.FetchRequest — do not rename without
// coordinating a server-side change.
type FetchModelRequest struct {
	Source      string   `json:"source"`
	ModelID     string   `json:"model_id"`
	Dest        string   `json:"dest,omitempty"`
	Patterns    []string `json:"patterns,omitempty"`
	MountSource string   `json:"mount_source,omitempty"`
	Subpath     string   `json:"subpath,omitempty"`
}

// ModelEntry describes a staged model on disk. Field tags mirror BONNIE's
// storage.Entry — do not rename without coordinating.
type ModelEntry struct {
	ID         string    `json:"id"`
	Source     string    `json:"source"`
	ModelID    string    `json:"model_id"`
	Path       string    `json:"path"`
	SizeBytes  int64     `json:"size_bytes"`
	Files      []string  `json:"files"`
	FetchedAt  time.Time `json:"fetched_at"`
	LastUsedAt time.Time `json:"last_used_at"`
}

// FetchModel stages a model on the host. The call is idempotent — the
// server no-ops when (source, model_id) already exists and returns the
// existing entry, so we retry on transient failures.
func (c *httpClient) FetchModel(ctx context.Context, req *FetchModelRequest) (*ModelEntry, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("bonnie: marshal fetch: %w", err)
	}
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodPost, path: "/api/v1/models/fetch", body: body,
		idempotent: true, op: "fetch model",
	})
	if err != nil {
		return nil, err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "fetch model"); err != nil {
		return nil, err
	}
	var out ModelEntry
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("bonnie: decode model entry: %w", err)
	}
	return &out, nil
}

// ListModels returns every staged model on the host.
func (c *httpClient) ListModels(ctx context.Context) ([]ModelEntry, error) {
	resp, err := c.do(ctx, requestOptions{
		method: http.MethodGet, path: "/api/v1/models", idempotent: true, op: "list models",
	})
	if err != nil {
		return nil, err
	}
	defer closeBody(resp)
	if err := checkStatus(resp, "list models"); err != nil {
		return nil, err
	}
	var out []ModelEntry
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("bonnie: decode models: %w", err)
	}
	return out, nil
}

// DeleteModel removes a staged model by id. DELETE is idempotent so we
// retry on transient failures.
func (c *httpClient) DeleteModel(ctx context.Context, id string) error {
	resp, err := c.do(ctx, requestOptions{
		method:     http.MethodDelete,
		path:       "/api/v1/models/" + url.PathEscape(id),
		idempotent: true,
		op:         "delete model",
	})
	if err != nil {
		return err
	}
	defer closeBody(resp)
	return checkStatus(resp, "delete model")
}
