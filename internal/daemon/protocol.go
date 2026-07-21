package daemon

import (
	"errors"
	"fmt"
	"strings"
	"unicode"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

const (
	ProtocolVersion = 1
	MaxRequestBytes = 64 << 10
)

type Operation string

const (
	HandshakeOperation   Operation = "handshake"
	StatusOperation      Operation = "status"
	PreSendOperation     Operation = "pre-send"
	PostFailureOperation Operation = "post-failure"
	PostSuccessOperation Operation = "post-success"
	UndoOperation        Operation = "undo"
	ConfirmOperation     Operation = "confirm"
	StopOperation        Operation = "stop"
)

type Request struct {
	Version       int       `json:"version"`
	Operation     Operation `json:"operation"`
	Shell         string    `json:"shell,omitempty"`
	Command       string    `json:"command,omitempty"`
	FailureOutput string    `json:"failure_output,omitempty"`
	Session       string    `json:"session,omitempty"`
	Token         string    `json:"token,omitempty"`
}

type Response struct {
	Version           int                 `json:"version"`
	Action            string              `json:"action"`
	Suggestion        string              `json:"suggestion,omitempty"`
	Explanation       string              `json:"explanation,omitempty"`
	Confidence        string              `json:"confidence,omitempty"`
	Risk              string              `json:"risk,omitempty"`
	Source            string              `json:"source,omitempty"`
	PackID            string              `json:"pack_id,omitempty"`
	RuleID            string              `json:"rule_id,omitempty"`
	Evidence          []diagnose.Evidence `json:"evidence,omitempty"`
	ConfirmationToken string              `json:"confirmation_token,omitempty"`
	UndoToken         string              `json:"undo_token,omitempty"`
	Error             string              `json:"error,omitempty"`
}

func (r Request) Validate() error {
	if r.Version != ProtocolVersion {
		return fmt.Errorf("unsupported daemon protocol version %d", r.Version)
	}
	if !validOperation(r.Operation) {
		return fmt.Errorf("unsupported daemon operation %q", r.Operation)
	}
	if len(r.Command)+len(r.FailureOutput)+len(r.Session)+len(r.Token) > MaxRequestBytes {
		return errors.New("daemon request exceeds size limit")
	}
	if strings.IndexByte(r.Session, 0) >= 0 || strings.IndexByte(r.Token, 0) >= 0 {
		return errors.New("daemon request contains invalid token data")
	}
	if containsUnsafeControl(r.FailureOutput) {
		return errors.New("daemon failure output contains control characters")
	}
	return nil
}

func containsUnsafeControl(value string) bool {
	for _, character := range value {
		if unicode.IsControl(character) && character != '\n' && character != '\r' && character != '\t' {
			return true
		}
	}
	return false
}

func (r Response) Validate() error {
	if r.Version != ProtocolVersion {
		return fmt.Errorf("unsupported daemon response version %d", r.Version)
	}
	if r.Action == "" {
		return errors.New("daemon response action is required")
	}
	return nil
}

func validOperation(operation Operation) bool {
	switch operation {
	case HandshakeOperation, StatusOperation, PreSendOperation, PostFailureOperation, PostSuccessOperation, UndoOperation, ConfirmOperation, StopOperation:
		return true
	default:
		return false
	}
}
