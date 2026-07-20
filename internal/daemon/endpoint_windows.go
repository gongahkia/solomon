//go:build windows

package daemon

import "errors"

func LocalEndpoint(_ string) (Endpoint, error) {
	return Endpoint{}, errors.New("Windows named-pipe transport is not implemented")
}
