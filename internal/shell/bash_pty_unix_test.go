//go:build !windows

package shell

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/creack/pty"
)

const bashPTYTimeout = 5 * time.Second

type bashPTYSession struct {
	command    *exec.Cmd
	terminal   *os.File
	mu         sync.Mutex
	output     string
	updated    chan struct{}
	terminated bool
}

func TestBashInteractivePTYInterruptPreventsExecution(t *testing.T) {
	session, marker := startBashPTY(t, "interrupt")
	start := session.write(t, "touch $MARKER\r")
	session.waitFor(t, "close-enough [safe/1]: keep buffer", start)
	session.waitFor(t, "\nCE> ", start)
	start = session.write(t, "\x03")
	session.waitFor(t, "\nCE> ", start)
	session.write(t, "\x15")
	session.stop(t)

	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("interrupt executed buffered command: %v\n%s", err, session.transcript())
	}
}

func TestBashInteractivePTYHintSubmitsCommand(t *testing.T) {
	session, marker := startBashPTY(t, "hint")
	start := session.write(t, "touch $MARKER\r")
	session.waitFor(t, "close-enough [safe/1]: keep buffer", start)
	session.waitFor(t, "\nCE> ", start)
	session.stop(t)

	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("hint did not submit buffered command: %v\n%s", err, session.transcript())
	}
}

func TestBashInteractivePTYDaemonFailureSubmitsCommand(t *testing.T) {
	session, marker := startBashPTY(t, "unavailable")
	start := session.write(t, "touch $MARKER\r")
	session.waitFor(t, "\nCE> ", start)
	session.stop(t)

	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("daemon failure did not submit buffered command: %v\n%s", err, session.transcript())
	}
}

func startBashPTY(t *testing.T, action string) (*bashPTYSession, string) {
	t.Helper()
	directory := t.TempDir()
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.bash")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	checkerScript := "#!/bin/sh\nexit 1\n"
	if action != "unavailable" {
		checkerScript = fmt.Sprintf("#!/bin/sh\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *\"--command exit\"*) printf '1\\tnone\\t\\t\\t\\t\\t\\n' ;; *) printf '1\\t%s\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n' ;; esac\n", action)
	}
	if err := os.WriteFile(checker, []byte(checkerScript), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	command := exec.Command("bash", "--noprofile", "--norc", "-i")
	command.Env = append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker, "TERM=dumb")
	terminal, err := pty.Start(command)
	if err != nil {
		t.Fatal(err)
	}
	session := &bashPTYSession{command: command, terminal: terminal, updated: make(chan struct{})}
	go session.recordOutput()
	t.Cleanup(func() {
		if !session.terminated {
			_ = session.terminal.Close()
			_ = session.command.Process.Kill()
			_ = session.command.Wait()
		}
	})

	start := session.write(t, "PS1='CE> '; PROMPT_COMMAND=\r")
	session.waitFor(t, "\nCE> ", start)
	start = session.write(t, "source $ADAPTER\r")
	session.waitFor(t, "\nCE> ", start)
	return session, marker
}

func (session *bashPTYSession) recordOutput() {
	buffer := make([]byte, 4096)
	for {
		count, err := session.terminal.Read(buffer)
		if count > 0 {
			session.mu.Lock()
			session.output += string(buffer[:count])
			close(session.updated)
			session.updated = make(chan struct{})
			session.mu.Unlock()
		}
		if err != nil {
			return
		}
	}
}

func (session *bashPTYSession) write(t *testing.T, input string) int {
	t.Helper()
	session.mu.Lock()
	start := len(session.output)
	session.mu.Unlock()
	if _, err := session.terminal.WriteString(input); err != nil {
		t.Fatalf("write PTY input %q: %v\n%s", input, err, session.transcript())
	}
	return start
}

func (session *bashPTYSession) waitFor(t *testing.T, text string, start int) {
	t.Helper()
	deadline := time.NewTimer(bashPTYTimeout)
	defer deadline.Stop()
	for {
		session.mu.Lock()
		output, updated := session.output, session.updated
		session.mu.Unlock()
		if strings.Contains(output[start:], text) {
			return
		}
		select {
		case <-updated:
		case <-deadline.C:
			t.Fatalf("timed out waiting for %q\n%s", text, session.transcript())
		}
	}
}

func (session *bashPTYSession) transcript() string {
	session.mu.Lock()
	defer session.mu.Unlock()
	return session.output
}

func (session *bashPTYSession) stop(t *testing.T) {
	t.Helper()
	session.write(t, "exit\r")
	result := make(chan error, 1)
	go func() { result <- session.command.Wait() }()
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("exit bash PTY: %v\n%s", err, session.transcript())
		}
	case <-time.After(bashPTYTimeout):
		_ = session.terminal.Close()
		_ = session.command.Process.Kill()
		<-result
		t.Fatalf("timed out exiting bash PTY\n%s", session.transcript())
	}
	if err := session.terminal.Close(); err != nil {
		t.Fatalf("close bash PTY: %v", err)
	}
	session.terminated = true
}
