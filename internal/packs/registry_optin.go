package packs

import "fmt"

type RegistryOptInState string
type RegistryOptInEvent string

const (
	RegistryDisabled RegistryOptInState = "disabled"
	RegistryPending  RegistryOptInState = "pending"
	RegistryEnabled  RegistryOptInState = "enabled"

	RegistryRequest RegistryOptInEvent = "request"
	RegistryConfirm RegistryOptInEvent = "confirm"
	RegistryRevoke  RegistryOptInEvent = "revoke"
)

func TransitionRegistryOptIn(state RegistryOptInState, event RegistryOptInEvent) (RegistryOptInState, error) {
	switch {
	case state == RegistryDisabled && event == RegistryRequest:
		return RegistryPending, nil
	case state == RegistryPending && event == RegistryConfirm:
		return RegistryEnabled, nil
	case (state == RegistryPending || state == RegistryEnabled) && event == RegistryRevoke:
		return RegistryDisabled, nil
	default:
		return state, fmt.Errorf("invalid registry opt-in transition %s -> %s", state, event)
	}
}

func (s RegistryOptInState) Allowed() bool { return s == RegistryEnabled }
