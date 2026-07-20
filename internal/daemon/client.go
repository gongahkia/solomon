package daemon

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"time"
)

type Client struct {
	Endpoint Endpoint
	Timeout  time.Duration
}

func (c Client) Request(ctx context.Context, request Request) (Response, error) {
	if err := request.Validate(); err != nil {
		return Response{}, err
	}
	timeout := c.Timeout
	if timeout <= 0 {
		timeout = 50 * time.Millisecond
	}
	dialer := net.Dialer{Timeout: timeout}
	connection, err := dialer.DialContext(ctx, c.Endpoint.Network, c.Endpoint.Address)
	if err != nil {
		return Response{}, errors.Join(ErrUnavailable, err)
	}
	defer connection.Close()
	deadline := time.Now().Add(timeout)
	if err := connection.SetDeadline(deadline); err != nil {
		return Response{}, err
	}
	if err := json.NewEncoder(connection).Encode(request); err != nil {
		return Response{}, errors.Join(ErrUnavailable, err)
	}
	var response Response
	if err := json.NewDecoder(connection).Decode(&response); err != nil {
		return Response{}, errors.Join(ErrUnavailable, err)
	}
	if err := response.Validate(); err != nil {
		return Response{}, err
	}
	return response, nil
}
