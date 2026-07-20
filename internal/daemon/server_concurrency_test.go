//go:build !windows

package daemon

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestServerIsolatesConcurrentRequests(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(endpoint, func(_ context.Context, request Request) (Response, error) {
		return Response{Version: ProtocolVersion, Action: "hint", Suggestion: request.Command}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	go server.Serve(context.Background())
	const requests = 32
	errors := make(chan error, requests)
	var group sync.WaitGroup
	for index := range requests {
		group.Add(1)
		go func(index int) {
			defer group.Done()
			command := fmt.Sprintf("git status %d", index)
			response, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: command})
			if err != nil {
				errors <- err
				return
			}
			if response.Action != "hint" || response.Suggestion != command {
				errors <- fmt.Errorf("response = %#v", response)
			}
		}(index)
	}
	group.Wait()
	close(errors)
	for err := range errors {
		t.Error(err)
	}
}
