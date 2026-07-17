package clierr

import (
	"errors"
)

type Kind string

const (
	Usage         Kind = "usage"
	Configuration Kind = "configuration"
	Input         Kind = "input"
	Operation     Kind = "operation"
	Internal      Kind = "internal"
)

const (
	ExitSuccess       = 0
	ExitInternal      = 1
	ExitUsage         = 2
	ExitConfiguration = 3
	ExitInput         = 4
	ExitOperation     = 5
)

type Error struct {
	Kind Kind
	Err  error
}

func (e *Error) Error() string { return e.Err.Error() }

func (e *Error) Unwrap() error { return e.Err }

func New(kind Kind, message string) error {
	return &Error{Kind: kind, Err: errors.New(message)}
}

func Wrap(kind Kind, err error) error {
	if err == nil {
		return nil
	}
	return &Error{Kind: kind, Err: err}
}

func Code(err error) int {
	if err == nil {
		return ExitSuccess
	}
	var typed *Error
	if !errors.As(err, &typed) {
		return ExitInternal
	}
	switch typed.Kind {
	case Usage:
		return ExitUsage
	case Configuration:
		return ExitConfiguration
	case Input:
		return ExitInput
	case Operation:
		return ExitOperation
	default:
		return ExitInternal
	}
}
