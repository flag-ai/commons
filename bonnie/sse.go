package bonnie

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"strings"
)

// parseSSE reads event-stream frames from r and dispatches them to
// onFrame. An SSE frame is one or more "event:" / "data:" lines
// terminated by a blank line. Consecutive data: lines are joined with
// \n per the W3C EventSource spec.
//
// Comment lines (leading ':') and unknown field names are ignored, as
// required by the spec. A canceled context terminates the scan on the
// next iteration.
func parseSSE(ctx context.Context, r io.Reader, onFrame func(event, data string) error) error {
	scanner := bufio.NewScanner(r)
	// SSE frames can be large (benchmark results JSON); bump the default
	// 64KiB token buffer to 1MiB to accommodate them.
	const maxScanTokenSize = 1024 * 1024
	scanner.Buffer(make([]byte, 0, 64*1024), maxScanTokenSize)

	var event, dataBuf string
	flush := func() error {
		if dataBuf == "" && event == "" {
			return nil
		}
		data := strings.TrimSuffix(dataBuf, "\n")
		err := onFrame(event, data)
		event = ""
		dataBuf = ""
		return err
	}

	for scanner.Scan() {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		line := scanner.Text()
		switch {
		case line == "":
			if err := flush(); err != nil {
				return err
			}
		case strings.HasPrefix(line, ":"):
			// Comment / heartbeat; ignore.
		case strings.HasPrefix(line, "event:"):
			event = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		case strings.HasPrefix(line, "data:"):
			// SSE spec: if the field value starts with a single space, strip it.
			v := strings.TrimPrefix(line, "data:")
			v = strings.TrimPrefix(v, " ")
			dataBuf += v + "\n"
		}
	}
	if err := flush(); err != nil {
		return err
	}
	if err := scanner.Err(); err != nil && ctx.Err() == nil {
		return fmt.Errorf("bonnie: sse scan: %w", err)
	}
	return nil
}
