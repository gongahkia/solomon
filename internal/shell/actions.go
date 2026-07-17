package shell

import (
	"fmt"
	"sync"
)

type ActionState string

const (
	ActionNone         ActionState = "none"
	ActionHint         ActionState = "hint"
	ActionInterrupt    ActionState = "interrupt"
	ActionRewrite      ActionState = "rewrite"
	ActionRunUnchanged ActionState = "run-unchanged"
	ActionEditInBuffer ActionState = "edit-in-buffer"
)

type ActionResult struct {
	Render  bool
	Submit  bool
	Rewrite bool
	Refused bool
}

func ResolveAction(action, risk, suggestion string) ActionResult {
	switch ActionState(action) {
	case ActionNone, ActionRunUnchanged:
		return ActionResult{Submit: true}
	case ActionHint:
		return ActionResult{Render: true, Submit: true}
	case ActionInterrupt:
		return ActionResult{Render: true}
	case ActionRewrite, ActionEditInBuffer:
		if risk == "safe" && suggestion != "" {
			return ActionResult{Rewrite: true}
		}
		return ActionResult{Render: true, Refused: true}
	default:
		return ActionResult{Submit: true}
	}
}

func InlineDiagnostic(risk, confidence, suggestion string) string {
	return fmt.Sprintf("close-enough [%s/%s]: %s", risk, confidence, suggestion)
}

type OneTimeAccept struct {
	mu       sync.Mutex
	accepted map[string]struct{}
}

func (a *OneTimeAccept) Accept(key string) bool {
	if key == "" {
		return false
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.accepted == nil {
		a.accepted = map[string]struct{}{}
	}
	if _, ok := a.accepted[key]; ok {
		return false
	}
	a.accepted[key] = struct{}{}
	return true
}
