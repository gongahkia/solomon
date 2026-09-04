package daemon

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gongahkia/solomon/internal/config"
	"github.com/gongahkia/solomon/internal/diagnose"
	"github.com/gongahkia/solomon/internal/localstate"
	"github.com/gongahkia/solomon/internal/packs"
	"github.com/gongahkia/solomon/internal/redact"
)

type Service struct {
	Engine        diagnose.Engine
	Config        config.Config
	Packs         packs.RuntimeResolver
	Store         *localstate.Store
	LearnedRules  []localstate.LearnedRule
	mu            sync.Mutex
	confirmations map[string]confirmation
	undos         map[string]pendingUndo
	failures      map[string]failure
	now           func() time.Time
}

type confirmation struct {
	command string
	token   string
	expires time.Time
}

type failure struct {
	command string
	output  string
	created time.Time
}

type pendingUndo struct {
	session string
	command string
	expires time.Time
}

const maxFailureOutputBytes = 8 << 10
const learningPairWindow = 5 * time.Minute

func (s *Service) Handle(ctx context.Context, request Request) (Response, error) {
	switch request.Operation {
	case HandshakeOperation:
		return Response{Version: ProtocolVersion, Action: "ready"}, nil
	case StatusOperation:
		return Response{Version: ProtocolVersion, Action: "ready"}, nil
	case PreSendOperation:
		s.clearPendingUndo(request.Session)
		response, err := s.preSend(ctx, request)
		if err != nil {
			return Response{}, err
		}
		return s.issueUndoToken(request, response), nil
	case PostFailureOperation:
		s.clearPendingUndo(request.Session)
		s.rememberFailure(request)
		response, ok, err := s.curatedDecision(ctx, request.Shell, request.Command, request.Session, "post")
		if err != nil {
			return Response{}, err
		}
		if ok {
			return s.attachKubernetesCloudFailureEvidence(request, s.attachContainerFailureEvidence(request, s.attachGoFailureEvidence(request, s.attachRustFailureEvidence(request, s.attachPythonFailureEvidence(request, s.attachJavaScriptFailureEvidence(request, s.attachPackageManagerFailureEvidence(request, s.attachGitFailureEvidence(request, response)))))))), nil
		}
		response, err = s.decision(ctx, request.Shell, request.Command, "post")
		if err != nil {
			return Response{}, err
		}
		return s.attachKubernetesCloudFailureEvidence(request, s.attachContainerFailureEvidence(request, s.attachGoFailureEvidence(request, s.attachRustFailureEvidence(request, s.attachPythonFailureEvidence(request, s.attachJavaScriptFailureEvidence(request, s.attachPackageManagerFailureEvidence(request, s.attachGitFailureEvidence(request, response)))))))), nil
	case PostSuccessOperation:
		s.clearPendingUndo(request.Session)
		s.recordSuccess(ctx, request)
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	case ConfirmOperation:
		if s.consumeConfirmationToken(request.Session, request.Command, request.Token) {
			return Response{Version: ProtocolVersion, Action: "submit"}, nil
		}
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	case UndoOperation:
		if s.Config.UndoEnabled {
			if pending, ok := s.consumeUndoToken(request.Session, request.Token); ok {
				return Response{Version: ProtocolVersion, Action: "edit-in-buffer", Suggestion: pending.command, Risk: string(diagnose.RiskSafe), Source: "undo"}, nil
			}
		}
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	case StopOperation:
		return Response{Version: ProtocolVersion, Action: "stopping"}, nil
	default:
		return Response{}, fmt.Errorf("unsupported daemon operation %q", request.Operation)
	}
}

func (s *Service) preSend(ctx context.Context, request Request) (Response, error) {
	if !diagnose.ShellCommandSupported(request.Shell, request.Command) {
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	}
	response, ok, err := s.curatedDecision(ctx, request.Shell, request.Command, request.Session, "pre")
	if err != nil {
		return Response{}, err
	}
	if ok {
		return response, nil
	}
	if response, ok := s.learnedDecision(request.Command, "pre"); ok {
		return response, nil
	}
	response, err = s.decision(ctx, request.Shell, request.Command, "pre")
	if err != nil || response.Action != "interrupt" {
		return response, err
	}
	if request.Session == "" {
		return response, nil
	}
	if s.consumeConfirmation(request.Session, request.Command) {
		response.Action = "submit"
		return response, nil
	}
	token, err := newConfirmationToken()
	if err != nil {
		return Response{}, err
	}
	s.storeConfirmation(request.Session, request.Command, token)
	response.ConfirmationToken = token
	return response, nil
}

func (s *Service) issueUndoToken(request Request, response Response) Response {
	if !s.Config.UndoEnabled || response.Action != "rewrite" || request.Session == "" || request.Command == "" {
		return response
	}
	token, err := newConfirmationToken()
	if err != nil {
		return response
	}
	s.storeUndoToken(token, request.Session, request.Command)
	response.UndoToken = token
	return response
}

func (s *Service) learnedDecision(command, stage string) (Response, bool) {
	if stage != "pre" || !s.Config.LocalLearningEnabled {
		return Response{}, false
	}
	failure, ok := normalizedLearningCommand(command)
	if !ok {
		return Response{}, false
	}
	for _, rule := range s.LearnedRules {
		if !rule.Enabled || rule.Failure != failure {
			continue
		}
		action := limitedLearnedAction(rule.Action, s.Config.LearnedRuleActionCeiling)
		if action == "off" {
			return Response{}, false
		}
		return Response{Version: ProtocolVersion, Action: action, Suggestion: rule.Correction, Explanation: "local learned repair", Confidence: "high", Risk: string(diagnose.RiskSafe), Source: "learned", RuleID: strconv.FormatInt(rule.ID, 10)}, true
	}
	return Response{}, false
}

func limitedLearnedAction(ruleAction, ceiling string) string {
	levels := map[string]int{"off": 0, "hint": 1, "rewrite": 2}
	ruleLevel, ruleOK := levels[ruleAction]
	ceilingLevel, ceilingOK := levels[ceiling]
	if !ruleOK || !ceilingOK {
		return "off"
	}
	if ruleLevel > ceilingLevel {
		ruleLevel = ceilingLevel
	}
	for action, level := range levels {
		if level == ruleLevel {
			return action
		}
	}
	return "off"
}

func (s *Service) rememberFailure(request Request) {
	if !s.Config.LocalLearningEnabled || s.Store == nil || request.Session == "" {
		return
	}
	command, ok := normalizedLearningCommand(request.Command)
	if !ok {
		return
	}
	output := safeFailureOutput(request.FailureOutput)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.failures == nil {
		s.failures = map[string]failure{}
	}
	now := s.currentTime()
	s.removeExpiredFailures(now)
	s.failures[failureKey(request.Session, request.Token)] = failure{command: command, output: output, created: now}
}

func (s *Service) attachGitFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || firstCommandWord(request.Command) != "git" {
		return response
	}
	evidence, err := packs.ExtractGitFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func (s *Service) attachPackageManagerFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || !isPackageManagerCommand(firstCommandWord(request.Command)) {
		return response
	}
	evidence, err := packs.ExtractPackageManagerFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func (s *Service) attachJavaScriptFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || !isJavaScriptCommand(firstCommandWord(request.Command)) {
		return response
	}
	evidence, err := packs.ExtractJavaScriptFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func (s *Service) attachPythonFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || !isPythonCommand(firstCommandWord(request.Command)) {
		return response
	}
	evidence, err := packs.ExtractPythonFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func (s *Service) attachRustFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || !isRustCommand(firstCommandWord(request.Command)) {
		return response
	}
	evidence, err := packs.ExtractRustFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func (s *Service) attachGoFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || !isGoCommand(firstCommandWord(request.Command)) {
		return response
	}
	evidence, err := packs.ExtractGoFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func (s *Service) attachContainerFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || !isContainerCommand(firstCommandWord(request.Command)) {
		return response
	}
	evidence, err := packs.ExtractContainerFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func (s *Service) attachKubernetesCloudFailureEvidence(request Request, response Response) Response {
	if response.Action == "none" || response.Suggestion == "" || !isKubernetesCloudCommand(firstCommandWord(request.Command)) {
		return response
	}
	evidence, err := packs.ExtractKubernetesCloudFailureEvidence(safeFailureOutput(request.FailureOutput))
	if err == nil {
		response.Evidence = evidence
	}
	return response
}

func isPackageManagerCommand(command string) bool {
	switch command {
	case "brew", "npm", "pnpm", "yarn":
		return true
	default:
		return false
	}
}

func isJavaScriptCommand(command string) bool {
	switch command {
	case "bun", "deno", "node":
		return true
	default:
		return false
	}
}

func isPythonCommand(command string) bool {
	switch command {
	case "pip", "pytest", "python", "uv":
		return true
	default:
		return false
	}
}

func isRustCommand(command string) bool {
	switch command {
	case "cargo", "rustc", "rustup":
		return true
	default:
		return false
	}
}

func isGoCommand(command string) bool {
	switch command {
	case "go", "gofmt":
		return true
	default:
		return false
	}
}

func isContainerCommand(command string) bool {
	switch command {
	case "docker", "podman":
		return true
	default:
		return false
	}
}

func isKubernetesCloudCommand(command string) bool {
	switch command {
	case "aws", "helm", "kubectl", "terraform":
		return true
	default:
		return false
	}
}

func safeFailureOutput(output string) string {
	output, _ = redact.Text(output)
	if len(output) > maxFailureOutputBytes {
		return output[:maxFailureOutputBytes]
	}
	return output
}

func firstCommandWord(command string) string {
	words := strings.Fields(command)
	if len(words) == 0 {
		return ""
	}
	return words[0]
}

func (s *Service) recordSuccess(ctx context.Context, request Request) {
	if !s.Config.LocalLearningEnabled || s.Store == nil || request.Session == "" {
		return
	}
	correction, ok := normalizedLearningCommand(request.Command)
	if !ok {
		return
	}
	s.mu.Lock()
	now := s.currentTime()
	s.removeExpiredFailures(now)
	key := failureKey(request.Session, request.Token)
	pending, exists := s.failures[key]
	if exists {
		delete(s.failures, key)
	}
	s.mu.Unlock()
	if !exists || pending.command == correction {
		return
	}
	_, _ = s.Store.RecordLearningPair(ctx, localstate.Observation{Session: request.Session, FailedCommand: pending.command, CorrectedCommand: correction, FailureOutput: pending.output, CreatedAt: now.UTC()})
}

func failureKey(session, token string) string { return session + "\x00" + token }

func (s *Service) removeExpiredFailures(now time.Time) {
	for key, pending := range s.failures {
		if now.After(pending.created.Add(learningPairWindow)) {
			delete(s.failures, key)
		}
	}
}

func normalizedLearningCommand(command string) (string, bool) {
	if len(command) == 0 || len(command) > 8<<10 {
		return "", false
	}
	words := strings.Fields(command)
	if len(words) == 0 {
		return "", false
	}
	value, containsSecret := redact.Command(words)
	return value, !containsSecret
}

// curatedDecision applies the same input and rendered-suggestion shell checks
// as diagnose.Engine before applying the explicit runtime mode policy.
func (s *Service) curatedDecision(ctx context.Context, shellName, command, session, stage string) (Response, bool, error) {
	if !diagnose.ShellCommandSupported(shellName, command) {
		return Response{}, false, nil
	}
	match, ok, err := s.Packs.MatchLineContext(ctx, command)
	if err != nil || !ok {
		return Response{}, ok, err
	}
	if !diagnose.ShellCommandSupported(shellName, match.Suggestion) {
		return Response{}, false, nil
	}
	suggestion, containsSecret := redact.Command(strings.Fields(match.Suggestion))
	risk := match.Risk
	if containsSecret {
		risk = string(diagnose.RiskHigh)
	}
	response := Response{Version: ProtocolVersion, Action: "hint", RewriteEligible: match.Source != "installed" && suggestion != "" && risk == string(diagnose.RiskSafe), Suggestion: suggestion, Explanation: match.Cause, Confidence: "high", Risk: risk, Source: "curated", PackID: match.PackID, RuleID: match.RuleID}
	if match.Source == "installed" {
		response.Source = "installed-pack"
	}
	if stage == "pre" && response.Risk == string(diagnose.RiskHigh) && (s.Config.Mode == "interrupt" || s.Config.Mode == "rewrite" && s.Config.RiskInterrupt) {
		if session == "" {
			return response, true, nil
		}
		if s.consumeConfirmation(session, command) {
			response.Action = "submit"
			return response, true, nil
		}
		token, err := newConfirmationToken()
		if err != nil {
			return Response{}, false, err
		}
		s.storeConfirmation(session, command, token)
		response.Action = "interrupt"
		response.ConfirmationToken = token
		return response, true, nil
	}
	if stage == "pre" && response.RewriteEligible && s.Config.Mode == "rewrite" && s.Config.AutoApplySafe {
		response.Action = "rewrite"
	}
	return response, true, nil
}

func (s *Service) decision(ctx context.Context, shellName, command, stage string) (Response, error) {
	decision, err := s.Engine.CheckShellContext(ctx, shellName, command, stage)
	if err != nil {
		return Response{}, err
	}
	response := Response{
		Version:         ProtocolVersion,
		Action:          decision.Action,
		RewriteEligible: decision.RewriteEligible,
		Suggestion:      decision.Suggestion,
		Explanation:     decision.Cause,
		Confidence:      strconv.FormatFloat(decision.Confidence, 'f', 2, 64),
		Risk:            string(decision.Risk),
		Source:          "heuristic",
	}
	if decision.Class == diagnose.RepairClassSemantic {
		response.Source = "curated"
		for _, evidence := range decision.Evidence {
			switch evidence.Kind {
			case "pack":
				response.PackID = evidence.Value
			case "rule":
				response.RuleID = evidence.Value
			case "source":
				if evidence.Value == "installed" {
					response.Source = "installed-pack"
				}
			}
		}
	}
	if response.Action == "" {
		response.Action = "none"
	}
	return response, nil
}

func (s *Service) consumeConfirmation(session, command string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	pending, ok := s.confirmations[session]
	if !ok {
		return false
	}
	delete(s.confirmations, session)
	return pending.command == command && s.currentTime().Before(pending.expires)
}

func (s *Service) consumeConfirmationToken(session, command, token string) bool {
	if session == "" || command == "" || token == "" {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	pending, ok := s.confirmations[session]
	if !ok {
		return false
	}
	if !s.currentTime().Before(pending.expires) {
		delete(s.confirmations, session)
		return false
	}
	if pending.command != command || pending.token != token {
		return false
	}
	delete(s.confirmations, session)
	return true
}

func (s *Service) storeConfirmation(session, command, token string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.confirmations == nil {
		s.confirmations = map[string]confirmation{}
	}
	s.confirmations[session] = confirmation{command: command, token: token, expires: s.currentTime().Add(5 * time.Second)}
}

func (s *Service) storeUndoToken(token, session, command string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.undos == nil {
		s.undos = map[string]pendingUndo{}
	}
	now := s.currentTime()
	s.removeExpiredUndos(now)
	for existingToken, pending := range s.undos {
		if pending.session == session {
			delete(s.undos, existingToken)
		}
	}
	s.undos[token] = pendingUndo{session: session, command: command, expires: now.Add(time.Duration(s.Config.UndoTTLSeconds) * time.Second)}
}

func (s *Service) consumeUndoToken(session, token string) (pendingUndo, bool) {
	if session == "" || token == "" {
		return pendingUndo{}, false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.currentTime()
	s.removeExpiredUndos(now)
	pending, ok := s.undos[token]
	if !ok || pending.session != session {
		return pendingUndo{}, false
	}
	delete(s.undos, token)
	return pending, true
}

func (s *Service) clearPendingUndo(session string) {
	if session == "" {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for token, pending := range s.undos {
		if pending.session == session {
			delete(s.undos, token)
		}
	}
}

func (s *Service) removeExpiredUndos(now time.Time) {
	for token, pending := range s.undos {
		if !now.Before(pending.expires) {
			delete(s.undos, token)
		}
	}
}

func (s *Service) currentTime() time.Time {
	if s.now != nil {
		return s.now()
	}
	return time.Now()
}

func newConfirmationToken() (string, error) {
	bytes := make([]byte, 16)
	if _, err := rand.Read(bytes); err != nil {
		return "", err
	}
	return hex.EncodeToString(bytes), nil
}
