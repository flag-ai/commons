package bonnie

import (
	"context"
	"io"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// parseSSE is unexported, so this test lives in the bonnie package.

func TestParseSSE_BasicFrames(t *testing.T) {
	t.Parallel()
	input := "data: one\n\ndata: two\n\n"
	var got []string
	err := parseSSE(context.Background(), strings.NewReader(input), func(_, data string) error {
		got = append(got, data)
		return nil
	})
	require.NoError(t, err)
	assert.Equal(t, []string{"one", "two"}, got)
}

func TestParseSSE_MultilineData(t *testing.T) {
	t.Parallel()
	input := "data: line 1\ndata: line 2\n\n"
	var frames [][2]string
	err := parseSSE(context.Background(), strings.NewReader(input), func(event, data string) error {
		frames = append(frames, [2]string{event, data})
		return nil
	})
	require.NoError(t, err)
	require.Len(t, frames, 1)
	assert.Equal(t, "line 1\nline 2", frames[0][1])
}

func TestParseSSE_Comments(t *testing.T) {
	t.Parallel()
	input := ": heartbeat\ndata: hi\n\n: another\ndata: world\n\n"
	var got []string
	err := parseSSE(context.Background(), strings.NewReader(input), func(_, data string) error {
		got = append(got, data)
		return nil
	})
	require.NoError(t, err)
	assert.Equal(t, []string{"hi", "world"}, got)
}

func TestParseSSE_EventAndData(t *testing.T) {
	t.Parallel()
	input := "event: done\ndata: {\"exit_code\":0}\n\n"
	var frames [][2]string
	err := parseSSE(context.Background(), strings.NewReader(input), func(event, data string) error {
		frames = append(frames, [2]string{event, data})
		return nil
	})
	require.NoError(t, err)
	require.Len(t, frames, 1)
	assert.Equal(t, "done", frames[0][0])
	assert.Equal(t, `{"exit_code":0}`, frames[0][1])
}

func TestParseSSE_NoTrailingBlankLine(t *testing.T) {
	t.Parallel()
	input := "data: trailing\n"
	var got []string
	err := parseSSE(context.Background(), strings.NewReader(input), func(_, data string) error {
		got = append(got, data)
		return nil
	})
	require.NoError(t, err)
	assert.Equal(t, []string{"trailing"}, got)
}

func TestParseSSE_ContextCancel(t *testing.T) {
	t.Parallel()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := parseSSE(ctx, strings.NewReader("data: x\n\n"), func(_, _ string) error {
		t.Fatal("onFrame should not be called after ctx cancel")
		return nil
	})
	// Cancellation before any scan means scanner may still return one
	// line; accept either the ctx error or clean exit.
	if err != nil {
		assert.Equal(t, context.Canceled, err)
	}
}

func TestParseSSE_ForwardsCallbackError(t *testing.T) {
	t.Parallel()
	want := io.EOF
	err := parseSSE(context.Background(), strings.NewReader("data: x\n\n"), func(_, _ string) error {
		return want
	})
	require.ErrorIs(t, err, want)
}
