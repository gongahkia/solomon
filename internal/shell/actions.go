package shell

import (
	"fmt"
	"strings"
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
	ActionSkipOnce     ActionState = "skip-once"
)

type ActionResult struct {
	Render  bool
	Submit  bool
	Rewrite bool
	Refused bool
}

func ResolveAction(action, risk, suggestion string) ActionResult {
	switch ActionState(action) {
	case ActionNone, ActionRunUnchanged, ActionSkipOnce:
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

type SkipOnce struct {
	mu      sync.Mutex
	skipped map[string]struct{}
}

type RuleSuppressions struct {
	mu    sync.RWMutex
	rules map[string]struct{}
}

type SafeRuleAcceptances struct {
	mu    sync.RWMutex
	rules map[string]struct{}
}

func (a *SafeRuleAcceptances) Accept(rule, risk string) bool {
	rule = strings.TrimSpace(rule)
	if rule == "" || risk != "safe" {
		return false
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.rules == nil {
		a.rules = map[string]struct{}{}
	}
	if _, ok := a.rules[rule]; ok {
		return false
	}
	a.rules[rule] = struct{}{}
	return true
}

func (a *SafeRuleAcceptances) Accepted(rule string) bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	_, ok := a.rules[strings.TrimSpace(rule)]
	return ok
}

func (s *RuleSuppressions) Suppress(rule string) bool {
	rule = strings.TrimSpace(rule)
	if rule == "" {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.rules == nil {
		s.rules = map[string]struct{}{}
	}
	if _, ok := s.rules[rule]; ok {
		return false
	}
	s.rules[rule] = struct{}{}
	return true
}

func (s *RuleSuppressions) Suppressed(rule string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	_, ok := s.rules[strings.TrimSpace(rule)]
	return ok
}

func (s *SkipOnce) Skip(key string) bool {
	if key == "" {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.skipped == nil {
		s.skipped = map[string]struct{}{}
	}
	if _, ok := s.skipped[key]; ok {
		return false
	}
	s.skipped[key] = struct{}{}
	return true
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
