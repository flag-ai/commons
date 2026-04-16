package bonnie

import "errors"

// Registry-level sentinels. Kept separate from the client errors file so
// they don't clutter BonnieError's semantics.
var (
	errNoAgentsRegistered = errors.New("bonnie: no agents registered")
	errNoOnlineAgents     = errors.New("bonnie: no online agents")
)
