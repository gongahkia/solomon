package daemon

import (
	"context"
	"errors"
	"net"
	"os"
	"sync"
	"syscall"
)

type Handler func(context.Context, Request) (Response, error)

type Server struct {
	endpoint Endpoint
	handler  Handler
	listener net.Listener
	mu       sync.Mutex
}

func NewServer(endpoint Endpoint, handler Handler) (*Server, error) {
	if endpoint.Network == "" || endpoint.Address == "" {
		return nil, errors.New("daemon endpoint is required")
	}
	if handler == nil {
		return nil, errors.New("daemon handler is required")
	}
	return &Server{endpoint: endpoint, handler: handler}, nil
}

func (s *Server) Listen() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.listener != nil {
		return ErrAlreadyRunning
	}
	if s.endpoint.Network == "unix" {
		if err := removeStaleSocket(s.endpoint.Address); err != nil {
			return err
		}
	}
	listener, err := listenEndpoint(s.endpoint)
	if err != nil {
		if errors.Is(err, syscall.EADDRINUSE) {
			return errors.Join(ErrAlreadyRunning, err)
		}
		return err
	}
	if s.endpoint.Network == "unix" {
		if err := os.Chmod(s.endpoint.Address, 0o600); err != nil {
			listener.Close()
			return err
		}
	}
	s.listener = listener
	return nil
}
