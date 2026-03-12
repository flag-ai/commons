package install_test

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/flag-ai/commons/install"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestScriptHandler_RendersTemplate(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{
		GenerateToken: func(_ *http.Request) (string, error) {
			return "testtokenabc123", nil
		},
		ServerURL: func(_ *http.Request) string {
			return "https://karr.example.com"
		},
		BinaryRepo: "flag-ai/bonnie",
		Port:       7777,
	})

	req := httptest.NewRequest(http.MethodGet, "/install.sh?token=testtokenabc123", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "text/x-shellscript", rec.Header().Get("Content-Type"))

	body := rec.Body.String()
	assert.Contains(t, body, `REPO="flag-ai/bonnie"`)
	assert.Contains(t, body, `SERVER_URL="https://karr.example.com"`)
	assert.Contains(t, body, `REGISTRATION_TOKEN="testtokenabc123"`)
	assert.Contains(t, body, `PORT="7777"`)
	assert.Contains(t, body, "#!/usr/bin/env bash")
}

func TestScriptHandler_Defaults(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{
		GenerateToken: func(_ *http.Request) (string, error) {
			return "tok123", nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	req.Host = "karr.internal:8080"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	body := rec.Body.String()
	assert.Contains(t, body, `REPO="flag-ai/bonnie"`)
	assert.Contains(t, body, `PORT="7777"`)
	assert.Contains(t, body, `SERVER_URL="http://karr.internal:8080"`)
}

func TestScriptHandler_XForwardedProto(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{
		GenerateToken: func(_ *http.Request) (string, error) {
			return "tok123", nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	req.Host = "karr.example.com"
	req.Header.Set("X-Forwarded-Proto", "https")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Contains(t, rec.Body.String(), `SERVER_URL="https://karr.example.com"`)
}

func TestScriptHandler_XForwardedProtoInvalid(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{
		GenerateToken: func(_ *http.Request) (string, error) {
			return "tok123", nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	req.Host = "karr.example.com"
	req.Header.Set("X-Forwarded-Proto", "ftp")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	// Invalid proto should fall back to "http"
	assert.Contains(t, rec.Body.String(), `SERVER_URL="http://karr.example.com"`)
}

func TestScriptHandler_TLSDetection(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{
		GenerateToken: func(_ *http.Request) (string, error) {
			return "tok123", nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	req.Host = "karr.example.com"
	req.TLS = &tls.ConnectionState{}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Contains(t, rec.Body.String(), `SERVER_URL="https://karr.example.com"`)
}

func TestScriptHandler_TokenError(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{
		GenerateToken: func(_ *http.Request) (string, error) {
			return "", fmt.Errorf("invalid or expired token")
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusBadRequest, rec.Code)
	assert.Contains(t, rec.Body.String(), "invalid or expired token")
}

func TestScriptHandler_TokenWithShellMetachars(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{
		GenerateToken: func(_ *http.Request) (string, error) {
			return `"; rm -rf / #`, nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusBadRequest, rec.Code)
	assert.Contains(t, rec.Body.String(), "invalid token format")
}

func TestScriptHandler_NilGenerateToken(t *testing.T) {
	t.Parallel()

	handler := install.ScriptHandler(install.HandlerConfig{})

	req := httptest.NewRequest(http.MethodGet, "/install.sh", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusInternalServerError, rec.Code)
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func TestRegisterHandler_Success(t *testing.T) {
	t.Parallel()

	handler := install.RegisterHandler(func(ctx context.Context, req install.RegisterRequest, sourceIP string) (install.RegisterResult, error) {
		assert.NotNil(t, ctx)
		assert.Equal(t, "regtok123", req.RegistrationToken)
		assert.Equal(t, 7777, req.Port)
		assert.Equal(t, "authtok456", req.AuthToken)
		assert.Equal(t, "192.168.1.100", sourceIP)
		return install.RegisterResult{
			AgentID: "agent-uuid-789",
			Message: "agent registered",
		}, nil
	}, discardLogger())

	body := `{"registration_token":"regtok123","port":7777,"auth_token":"authtok456"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/agents/register", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.RemoteAddr = "192.168.1.100:54321"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusCreated, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))

	var result install.RegisterResult
	require.NoError(t, json.NewDecoder(rec.Body).Decode(&result))
	assert.Equal(t, "agent-uuid-789", result.AgentID)
	assert.Equal(t, "agent registered", result.Message)
}

func TestRegisterHandler_WithAddressOverride(t *testing.T) {
	t.Parallel()

	handler := install.RegisterHandler(func(_ context.Context, req install.RegisterRequest, _ string) (install.RegisterResult, error) {
		assert.Equal(t, "10.0.0.50", req.Address)
		return install.RegisterResult{AgentID: "id"}, nil
	}, discardLogger())

	body := `{"registration_token":"tok","port":7777,"auth_token":"auth","address":"10.0.0.50"}`
	req := httptest.NewRequest(http.MethodPost, "/register", strings.NewReader(body))
	req.RemoteAddr = "192.168.1.1:1234"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusCreated, rec.Code)
}

func TestRegisterHandler_XForwardedFor(t *testing.T) {
	t.Parallel()

	var capturedIP string
	handler := install.RegisterHandler(func(_ context.Context, _ install.RegisterRequest, sourceIP string) (install.RegisterResult, error) {
		capturedIP = sourceIP
		return install.RegisterResult{AgentID: "id"}, nil
	}, discardLogger())

	body := `{"registration_token":"tok","port":7777,"auth_token":"auth"}`
	req := httptest.NewRequest(http.MethodPost, "/register", strings.NewReader(body))
	req.Header.Set("X-Forwarded-For", "203.0.113.50, 10.0.0.1")
	req.RemoteAddr = "10.0.0.1:5555"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusCreated, rec.Code)
	assert.Equal(t, "203.0.113.50", capturedIP)
}

func TestRegisterHandler_RemoteAddrNoPort(t *testing.T) {
	t.Parallel()

	var capturedIP string
	handler := install.RegisterHandler(func(_ context.Context, _ install.RegisterRequest, sourceIP string) (install.RegisterResult, error) {
		capturedIP = sourceIP
		return install.RegisterResult{AgentID: "id"}, nil
	}, discardLogger())

	body := `{"registration_token":"tok","port":7777,"auth_token":"auth"}`
	req := httptest.NewRequest(http.MethodPost, "/register", strings.NewReader(body))
	req.RemoteAddr = "192.168.1.1"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusCreated, rec.Code)
	assert.Equal(t, "192.168.1.1", capturedIP)
}

func TestRegisterHandler_MissingFields(t *testing.T) {
	t.Parallel()

	handler := install.RegisterHandler(func(_ context.Context, _ install.RegisterRequest, _ string) (install.RegisterResult, error) {
		t.Fatal("callback should not be called")
		return install.RegisterResult{}, nil
	}, discardLogger())

	tests := []struct {
		name string
		body string
	}{
		{"missing token", `{"port":7777,"auth_token":"auth"}`},
		{"missing auth", `{"registration_token":"tok","port":7777}`},
		{"missing port", `{"registration_token":"tok","auth_token":"auth"}`},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			req := httptest.NewRequest(http.MethodPost, "/register", strings.NewReader(tc.body))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusBadRequest, rec.Code)
		})
	}
}

func TestRegisterHandler_InvalidPort(t *testing.T) {
	t.Parallel()

	handler := install.RegisterHandler(func(_ context.Context, _ install.RegisterRequest, _ string) (install.RegisterResult, error) {
		t.Fatal("callback should not be called")
		return install.RegisterResult{}, nil
	}, discardLogger())

	tests := []struct {
		name string
		body string
	}{
		{"port too high", `{"registration_token":"tok","port":70000,"auth_token":"auth"}`},
		{"port negative", `{"registration_token":"tok","port":-1,"auth_token":"auth"}`},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			req := httptest.NewRequest(http.MethodPost, "/register", strings.NewReader(tc.body))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusBadRequest, rec.Code)
		})
	}
}

func TestRegisterHandler_InvalidJSON(t *testing.T) {
	t.Parallel()

	handler := install.RegisterHandler(func(_ context.Context, _ install.RegisterRequest, _ string) (install.RegisterResult, error) {
		return install.RegisterResult{}, nil
	}, discardLogger())

	req := httptest.NewRequest(http.MethodPost, "/register", strings.NewReader("not json"))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusBadRequest, rec.Code)
}

func TestRegisterHandler_MethodNotAllowed(t *testing.T) {
	t.Parallel()

	handler := install.RegisterHandler(func(_ context.Context, _ install.RegisterRequest, _ string) (install.RegisterResult, error) {
		return install.RegisterResult{}, nil
	}, discardLogger())

	req := httptest.NewRequest(http.MethodGet, "/register", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusMethodNotAllowed, rec.Code)
}

func TestRegisterHandler_CallbackError(t *testing.T) {
	t.Parallel()

	handler := install.RegisterHandler(func(_ context.Context, _ install.RegisterRequest, _ string) (install.RegisterResult, error) {
		return install.RegisterResult{}, fmt.Errorf("token expired or already claimed")
	}, discardLogger())

	body := `{"registration_token":"tok","port":7777,"auth_token":"auth"}`
	req := httptest.NewRequest(http.MethodPost, "/register", strings.NewReader(body))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnprocessableEntity, rec.Code)
	// Error message should be generic, not leak callback internals
	assert.Contains(t, rec.Body.String(), "registration failed")
	assert.NotContains(t, rec.Body.String(), "token expired")
}
