package daemon

import "errors"

var (
	ErrUnavailable    = errors.New("local daemon is unavailable")
	ErrAlreadyRunning = errors.New("local daemon is already running")
	ErrNotRunning     = errors.New("local daemon is not running")
	ErrStaleEndpoint  = errors.New("local daemon endpoint is stale")
)
