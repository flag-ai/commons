// Package version provides build-time version information for FLAG components.
//
// Variables are set via ldflags at build time:
//
//	go build -ldflags "-X github.com/flag-ai/commons/version.Version=1.0.0 -X github.com/flag-ai/commons/version.Commit=abc123 -X github.com/flag-ai/commons/version.Date=2025-01-01"
package version

import "fmt"

// Build-time variables set via ldflags.
var (
	Version = "dev"
	Commit  = "unknown"
	Date    = "unknown"
)

// Info returns a formatted version string.
func Info() string {
	return fmt.Sprintf("%s (commit: %s, built: %s)", Version, Commit, Date)
}
