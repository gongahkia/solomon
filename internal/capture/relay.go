package capture

import (
	"errors"
	"io"
	"net"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/gongahkia/close-enough/internal/redact"
)

const MaxOutputBytes = 8 << 10

var terminalControl = regexp.MustCompile(`\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))`)

// Relay keeps only redacted output from the command following its marker.
// The marker is written by an opt-in shell adapter into a pseudoterminal
// transcript; no transcript is persisted to disk.
type Relay struct {
	listener *net.UnixListener
	marker   string

	mu      sync.Mutex
	pending string
	output  string
	active  bool
}

func Start(socket, token string) (*Relay, error) {
	if socket == "" || token == "" {
		return nil, errors.New("capture socket and token are required")
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: socket, Net: "unix"})
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(socket, 0o600); err != nil {
		_ = listener.Close()
		return nil, err
	}
	relay := &Relay{listener: listener, marker: "\x1b]1337;CloseEnough=" + token + "\a"}
	go relay.serve()
	return relay, nil
}

func (r *Relay) Close() error {
	if r == nil || r.listener == nil {
		return nil
	}
	return r.listener.Close()
}

func (r *Relay) serve() {
	for {
		connection, err := r.listener.AcceptUnix()
		if err != nil {
			return
		}
		go r.serveConnection(connection)
	}
}

func (r *Relay) serveConnection(connection *net.UnixConn) {
	defer connection.Close()
	_ = connection.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
	request, _ := io.ReadAll(io.LimitReader(connection, 8<<10))
	if string(request) == "reset" {
		r.Reset()
		return
	}
	_, _ = connection.Write([]byte(r.Snapshot(string(request))))
}

func (r *Relay) FeedReader(reader io.Reader) error {
	buffer := make([]byte, 4096)
	for {
		count, err := reader.Read(buffer)
		if count > 0 {
			r.Feed(string(buffer[:count]))
		}
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
	}
}

func (r *Relay) Feed(value string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.pending += value
	for {
		index := strings.Index(r.pending, r.marker)
		if index < 0 {
			keep := len(r.marker) - 1
			if keep < 0 {
				keep = 0
			}
			if len(r.pending) <= keep {
				return
			}
			r.appendLocked(r.pending[:len(r.pending)-keep])
			r.pending = r.pending[len(r.pending)-keep:]
			return
		}
		if r.active {
			r.appendLocked(r.pending[:index])
		}
		r.output = ""
		r.active = true
		r.pending = r.pending[index+len(r.marker):]
	}
}

func (r *Relay) Reset() {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.pending = ""
	r.output = ""
	r.active = false
}

func (r *Relay) appendLocked(value string) {
	if !r.active || value == "" {
		return
	}
	value = terminalText(value)
	value, _ = redact.Text(value)
	r.output += value
	if len(r.output) > MaxOutputBytes {
		r.output = r.output[len(r.output)-MaxOutputBytes:]
	}
}

func (r *Relay) Snapshot(command string) string {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.active && r.pending != "" {
		r.appendLocked(r.pending)
		r.pending = ""
	}
	output := strings.TrimSpace(r.output)
	// Bash marks the prompt before Readline echoes the command. Zsh marks in
	// preexec, so this removal is a no-op there. Only remove the first echo.
	if command != "" {
		output = strings.TrimSpace(strings.TrimPrefix(output, command))
	}
	return output
}

func terminalText(value string) string {
	value = terminalControl.ReplaceAllString(value, "")
	return strings.Map(func(character rune) rune {
		if character == '\n' || character == '\t' || character == '\r' {
			return character
		}
		if unicode.IsControl(character) || unicode.Is(unicode.Bidi_Control, character) {
			return -1
		}
		return character
	}, value)
}

func Read(socket, command string) (string, error) {
	return request(socket, command)
}

func Reset(socket string) error {
	_, err := request(socket, "reset")
	return err
}

func request(socket, value string) (string, error) {
	connection, err := net.DialTimeout("unix", socket, 200*time.Millisecond)
	if err != nil {
		return "", err
	}
	defer connection.Close()
	if _, err := connection.Write([]byte(value)); err != nil {
		return "", err
	}
	if unixConnection, ok := connection.(*net.UnixConn); ok {
		if err := unixConnection.CloseWrite(); err != nil {
			return "", err
		}
	}
	_ = connection.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
	data, err := io.ReadAll(io.LimitReader(connection, MaxOutputBytes+1))
	if err != nil {
		return "", err
	}
	if len(data) > MaxOutputBytes {
		return "", errors.New("capture response exceeds limit")
	}
	return string(data), nil
}
