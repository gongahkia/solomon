package packs

import "fmt"

type AutoUpdateOptInState string
type AutoUpdateOptInEvent string

const (
	AutoUpdateDisabled AutoUpdateOptInState = "disabled"
	AutoUpdatePending  AutoUpdateOptInState = "pending"
	AutoUpdateEnabled  AutoUpdateOptInState = "enabled"

	AutoUpdateRequest AutoUpdateOptInEvent = "request"
	AutoUpdateConfirm AutoUpdateOptInEvent = "confirm"
	AutoUpdateRevoke  AutoUpdateOptInEvent = "revoke"
)

func TransitionAutoUpdateOptIn(state AutoUpdateOptInState, event AutoUpdateOptInEvent, registry RegistryOptInState) (AutoUpdateOptInState, error) {
	switch {
	case state == AutoUpdateDisabled && event == AutoUpdateRequest:
		return AutoUpdatePending, nil
	case state == AutoUpdatePending && event == AutoUpdateConfirm && registry.Allowed():
		return AutoUpdateEnabled, nil
	case (state == AutoUpdatePending || state == AutoUpdateEnabled) && event == AutoUpdateRevoke:
		return AutoUpdateDisabled, nil
	default:
		return state, fmt.Errorf("invalid auto-update opt-in transition %s -> %s", state, event)
	}
}

func (s AutoUpdateOptInState) Allowed() bool { return s == AutoUpdateEnabled }
