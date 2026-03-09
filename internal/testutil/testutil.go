// Package testutil provides shared test helpers for FLAG commons packages.
package testutil

import (
	"os"
	"testing"
)

// SetEnv sets an environment variable for the duration of a test and restores it on cleanup.
func SetEnv(t *testing.T, key, value string) {
	t.Helper()
	prev, existed := os.LookupEnv(key)
	t.Setenv(key, value)
	t.Cleanup(func() {
		if existed {
			os.Setenv(key, prev)
		} else {
			os.Unsetenv(key)
		}
	})
}

// UnsetEnv unsets an environment variable for the duration of a test and restores it on cleanup.
func UnsetEnv(t *testing.T, key string) {
	t.Helper()
	prev, existed := os.LookupEnv(key)
	os.Unsetenv(key)
	t.Cleanup(func() {
		if existed {
			os.Setenv(key, prev)
		}
	})
}
