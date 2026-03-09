package version_test

import (
	"testing"

	"github.com/flag-ai/commons/version"
	"github.com/stretchr/testify/assert"
)

func TestInfo_Defaults(t *testing.T) {
	info := version.Info()
	assert.Contains(t, info, "dev")
	assert.Contains(t, info, "unknown")
}

func TestInfo_CustomValues(t *testing.T) {
	orig := struct{ v, c, d string }{version.Version, version.Commit, version.Date}
	t.Cleanup(func() {
		version.Version = orig.v
		version.Commit = orig.c
		version.Date = orig.d
	})

	version.Version = "1.2.3"
	version.Commit = "abc123"
	version.Date = "2025-06-01"

	info := version.Info()
	assert.Equal(t, "1.2.3 (commit: abc123, built: 2025-06-01)", info)
}
