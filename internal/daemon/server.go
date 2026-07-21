package daemon

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"syscall"
	"time"
)

const requestDeadline = 50 * time.Millisecond

func (s *Server) Serve(ctx context.Context) error {
	s.mu.Lock()
	listener := s.listener
	s.mu.Unlock()
	if listener == nil {
		return errors.New("daemon server is not listening")
	}
	go func() {
		<-ctx.Done()
		_ = s.Close()
	}()
	for {
		connection, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		go s.serveConnection(ctx, connection)
	}
}

func (s *Server) Close() error {
	s.mu.Lock()
	listener := s.listener
	s.listener = nil
	s.mu.Unlock()
	if listener == nil {
		return nil
	}
	err := listener.Close()
	if s.endpoint.Network == "unix" {
		if removeErr := removeStaleSocket(s.endpoint.Address); removeErr != nil && !errors.Is(removeErr, os.ErrNotExist) {
			return errors.Join(err, removeErr)
		}
	}
	return err
}

func (s *Server) serveConnection(parent context.Context, connection net.Conn) {
	defer connection.Close()
	if err := connection.SetDeadline(time.Now().Add(requestDeadline)); err != nil {
		return
	}
	decoder := json.NewDecoder(io.LimitReader(connection, MaxRequestBytes+1))
	var request Request
	if err := decoder.Decode(&request); err != nil {
		s.writeResponse(connection, Response{Version: ProtocolVersion, Action: "none", Error: "invalid daemon request"})
		return
	}
	if err := request.Validate(); err != nil {
		s.writeResponse(connection, Response{Version: ProtocolVersion, Action: "none", Error: err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(parent, requestDeadline)
	defer cancel()
	response, err := s.handler(ctx, request)
	if err != nil {
		s.writeResponse(connection, Response{Version: ProtocolVersion, Action: "none", Error: err.Error()})
		return
	}
	if err := response.Validate(); err != nil {
		s.writeResponse(connection, Response{Version: ProtocolVersion, Action: "none", Error: fmt.Sprintf("invalid daemon response: %v", err)})
		return
	}
	s.writeResponse(connection, response)
	if request.Operation == StopOperation {
		go s.Close()
	}
}

func (s *Server) writeResponse(connection net.Conn, response Response) {
	_ = json.NewEncoder(connection).Encode(response)
}

func removeStaleSocket(path string) error {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSocket == 0 {
		return errors.New("daemon endpoint is not a socket")
	}
	connection, err := net.DialTimeout("unix", path, requestDeadline)
	if err == nil {
		connection.Close()
		return ErrAlreadyRunning
	}
	if !errors.Is(err, syscall.ECONNREFUSED) {
		return err
	}
	return os.Remove(path)
}
