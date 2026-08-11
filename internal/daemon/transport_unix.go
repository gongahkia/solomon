//go:build !windows

package daemon

import (
	"context"
	"net"
)

func listenEndpoint(endpoint Endpoint) (net.Listener, error) {
	return net.Listen(endpoint.Network, endpoint.Address)
}

func dialEndpoint(ctx context.Context, endpoint Endpoint) (net.Conn, error) {
	return (&net.Dialer{}).DialContext(ctx, endpoint.Network, endpoint.Address)
}
