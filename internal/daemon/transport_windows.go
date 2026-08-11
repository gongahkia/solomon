//go:build windows

package daemon

import (
	"context"
	"errors"
	"net"

	"github.com/Microsoft/go-winio"
	"golang.org/x/sys/windows"
)

const namedPipeSecurityDescriptor = "D:P(A;;GA;;;OW)"

func listenEndpoint(endpoint Endpoint) (net.Listener, error) {
	if endpoint.Network != "npipe" {
		return net.Listen(endpoint.Network, endpoint.Address)
	}
	listener, err := winio.ListenPipe(endpoint.Address, &winio.PipeConfig{SecurityDescriptor: namedPipeSecurityDescriptor})
	if errors.Is(err, windows.ERROR_ACCESS_DENIED) {
		return nil, errors.Join(ErrAlreadyRunning, err)
	}
	return listener, err
}

func dialEndpoint(ctx context.Context, endpoint Endpoint) (net.Conn, error) {
	if endpoint.Network == "npipe" {
		return winio.DialPipeContext(ctx, endpoint.Address)
	}
	return (&net.Dialer{}).DialContext(ctx, endpoint.Network, endpoint.Address)
}
