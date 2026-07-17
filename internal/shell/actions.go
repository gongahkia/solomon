package shell

import "fmt"

type ActionState string

const (
	ActionNone      ActionState = "none"
	ActionHint      ActionState = "hint"
	ActionInterrupt ActionState = "interrupt"
	ActionRewrite   ActionState = "rewrite"
)

type ActionResult struct {
	Render  bool
	Submit  bool
	Rewrite bool
	Refused bool
}

func ResolveAction(action, risk, suggestion string) ActionResult {
	switch ActionState(action) {
	case ActionNone:
		return ActionResult{Submit: true}
	case ActionHint:
		return ActionResult{Render: true, Submit: true}
	case ActionInterrupt:
		return ActionResult{Render: true}
	case ActionRewrite:
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
