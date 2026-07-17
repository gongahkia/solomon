package shell

import (
	"fmt"
	"sort"
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

type ConfirmationDialog struct {
	Required bool
	Message  string
}

func RiskConfirmation(risk, suggestion string) ConfirmationDialog {
	if risk == "safe" || suggestion == "" {
		return ConfirmationDialog{}
	}
	return ConfirmationDialog{Required: true, Message: fmt.Sprintf("confirm %s-risk repair: %s", risk, suggestion)}
}

const NonBlockingHintConfidence = 0.80

func LowConfidenceHint(confidence float64) ActionResult {
	if confidence >= 0 && confidence < NonBlockingHintConfidence {
		return ActionResult{Render: true, Submit: true}
	}
	return ActionResult{}
}

func LowConfidenceInterrupt(confidence float64, optedIn bool) ActionResult {
	if optedIn && confidence >= 0 && confidence < NonBlockingHintConfidence {
		return ActionResult{Render: true}
	}
	return ActionResult{}
}

func LowConfidenceKeybindingInterrupt(confidence float64, invoked bool) ActionResult {
	if invoked && confidence >= 0 && confidence < NonBlockingHintConfidence {
		return ActionResult{Render: true}
	}
	return ActionResult{}
}

const MaxSelectorCandidates = 5

func RenderCandidateSelector(candidates []string) string {
	unique := map[string]struct{}{}
	for _, candidate := range candidates {
		candidate = strings.TrimSpace(candidate)
		if candidate != "" {
			unique[candidate] = struct{}{}
		}
	}
	ordered := make([]string, 0, len(unique))
	for candidate := range unique {
		ordered = append(ordered, candidate)
	}
	sort.Strings(ordered)
	if len(ordered) > MaxSelectorCandidates {
		ordered = ordered[:MaxSelectorCandidates]
	}
	lines := make([]string, len(ordered))
	for index, candidate := range ordered {
		lines[index] = fmt.Sprintf("%d. %s", index+1, candidate)
	}
	return strings.Join(lines, "\n")
}

func TruncateForWidth(value string, width int) string {
	if width <= 0 {
		return ""
	}
	runes := []rune(value)
	if len(runes) <= width {
		return value
	}
	if width == 1 {
		return "…"
	}
	return string(runes[:width-1]) + "…"
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
