// Package install provides HTTP handlers for serving a BONNIE agent install
// script and processing agent self-registration callbacks.
package install

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"text/template"
)

//go:embed script.sh
var scriptSrc string

var scriptTmpl = template.Must(template.New("install").Parse(scriptSrc))

// HandlerConfig configures the install script handler.
type HandlerConfig struct {
	// GenerateToken extracts or validates a registration token from the request.
	// The returned token is embedded in the install script so the agent can
	// phone home with it.
	GenerateToken func(r *http.Request) (string, error)

	// ServerURL returns the base URL the install script should phone home to.
	// If nil, the URL is auto-detected from X-Forwarded-Proto + Host headers.
	ServerURL func(r *http.Request) string

	// BinaryRepo is the GitHub owner/repo for the BONNIE binary release.
	// Defaults to "flag-ai/bonnie".
	BinaryRepo string

	// Port is the BONNIE listen port written into the agent config.
	// Defaults to 7777.
	Port int
}

// scriptData is the template context for script.sh.
type scriptData struct {
	ServerURL         string
	RegistrationToken string
	BinaryRepo        string
	Port              int
}

// ScriptHandler returns an http.HandlerFunc that serves the install script.
// The script is rendered with the registration token and server URL embedded.
func ScriptHandler(cfg HandlerConfig) http.HandlerFunc {
	if cfg.BinaryRepo == "" {
		cfg.BinaryRepo = "flag-ai/bonnie"
	}
	if cfg.Port == 0 {
		cfg.Port = 7777
	}

	return func(w http.ResponseWriter, r *http.Request) {
		token, err := cfg.GenerateToken(r)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		serverURL := detectServerURL(r)
		if cfg.ServerURL != nil {
			serverURL = cfg.ServerURL(r)
		}

		var buf bytes.Buffer
		if err := scriptTmpl.Execute(&buf, scriptData{
			ServerURL:         serverURL,
			RegistrationToken: token,
			BinaryRepo:        cfg.BinaryRepo,
			Port:              cfg.Port,
		}); err != nil {
			http.Error(w, "failed to render install script", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "text/x-shellscript")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(buf.Bytes())
	}
}

// detectServerURL auto-detects the server base URL from request headers.
func detectServerURL(r *http.Request) string {
	scheme := "http"
	if proto := r.Header.Get("X-Forwarded-Proto"); proto != "" {
		scheme = proto
	} else if r.TLS != nil {
		scheme = "https"
	}
	return scheme + "://" + r.Host
}

// RegisterRequest is the JSON body sent by the install script when the agent
// phones home after installation.
type RegisterRequest struct {
	RegistrationToken string `json:"registration_token"`
	Port              int    `json:"port"`
	AuthToken         string `json:"auth_token"`
	Address           string `json:"address,omitempty"`
}

// RegisterResult is the JSON response returned to the install script.
type RegisterResult struct {
	AgentID string `json:"agent_id"`
	Message string `json:"message"`
}

// RegisterCallback is invoked by RegisterHandler after decoding the request
// and resolving the source address. The callback should validate the
// registration token, create the agent record, and return a result.
type RegisterCallback func(req RegisterRequest, sourceIP string) (RegisterResult, error)

// maxRegisterBody is the maximum allowed body size for registration (64 KiB).
const maxRegisterBody = 64 << 10

// RegisterHandler returns an http.HandlerFunc that processes agent
// self-registration POST requests. It decodes the JSON body, resolves the
// source IP, and delegates to the callback.
func RegisterHandler(cb RegisterCallback, logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		body := http.MaxBytesReader(w, r.Body, maxRegisterBody)
		defer func() { _ = body.Close() }()

		data, err := io.ReadAll(body)
		if err != nil {
			http.Error(w, "request body too large", http.StatusRequestEntityTooLarge)
			return
		}

		var req RegisterRequest
		if err := json.Unmarshal(data, &req); err != nil {
			writeJSONError(w, http.StatusBadRequest, "invalid JSON body")
			return
		}

		if req.RegistrationToken == "" || req.AuthToken == "" || req.Port == 0 {
			writeJSONError(w, http.StatusBadRequest, "registration_token, auth_token, and port are required")
			return
		}

		sourceIP := resolveSourceIP(r)

		result, err := cb(req, sourceIP)
		if err != nil {
			logger.Error("agent registration failed",
				slog.String("source_ip", sourceIP),
				slog.String("error", err.Error()),
			)
			writeJSONError(w, http.StatusUnprocessableEntity, err.Error())
			return
		}

		logger.Info("agent registered via install script",
			slog.String("agent_id", result.AgentID),
			slog.String("source_ip", sourceIP),
		)

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(result)
	}
}

// resolveSourceIP extracts the client IP from X-Forwarded-For or RemoteAddr.
func resolveSourceIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		// First entry is the original client.
		if ip := strings.TrimSpace(strings.SplitN(xff, ",", 2)[0]); ip != "" {
			return ip
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// writeJSONError writes a JSON error response.
func writeJSONError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
