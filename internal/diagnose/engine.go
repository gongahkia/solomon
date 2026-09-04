package diagnose

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/gongahkia/solomon/internal/config"
	"github.com/gongahkia/solomon/internal/redact"
)

type Risk string
type RepairClass string
type MessageKey string

type Evidence struct {
	Kind  string `json:"kind"`
	Value string `json:"value"`
}

const AdapterProtocolVersion = 1

const (
	MaxInputBytes       = 8 << 10
	MaxOutputBytes      = 8 << 10
	MaxAnalysisDuration = time.Second
	maxPathDirectories  = 64
	maxDirectoryEntries = 512
)

var (
	ErrInputLimit    = errors.New("diagnostic input exceeds size limit")
	ErrOutputLimit   = errors.New("diagnostic output exceeds size limit")
	ErrAnalysisLimit = errors.New("diagnostic analysis exceeds time limit")
)

const (
	RiskSafe    Risk = "safe"
	RiskUnknown Risk = "unknown"
	RiskHigh    Risk = "high"

	RepairClassCommand  RepairClass = "command"
	RepairClassSemantic RepairClass = "semantic"
	RepairClassPath     RepairClass = "path"
)

type consequenceTemplate struct {
	cause       MessageKey
	consequence MessageKey
}

const (
	MessageCauseCommandNotFound      MessageKey = "diagnostic.cause.command_not_found"
	MessageConsequenceCommandRejects MessageKey = "diagnostic.consequence.command_rejects"
	MessageCauseUnknownGitSubcommand MessageKey = "diagnostic.cause.unknown_git_subcommand"
	MessageConsequenceGitExits       MessageKey = "diagnostic.consequence.git_exits"
	MessageCausePathNotFound         MessageKey = "diagnostic.cause.path_not_found"
	MessageConsequencePathMayFail    MessageKey = "diagnostic.consequence.path_may_fail"
	MessageRiskSecret                MessageKey = "diagnostic.risk.secret"
	MessageRiskPrivilegeEscalation   MessageKey = "diagnostic.risk.privilege_escalation"
	MessageRiskNetworkEffect         MessageKey = "diagnostic.risk.network_effect"
	MessageRiskFilesystemMutation    MessageKey = "diagnostic.risk.filesystem_mutation"
	MessageRiskRecognizedSafe        MessageKey = "diagnostic.risk.recognized_safe"
	MessageRiskUnknown               MessageKey = "diagnostic.risk.unknown"
)

// #nosec G101 -- These diagnostics intentionally identify secret-bearing command arguments; they contain no credential values.
var defaultMessages = map[MessageKey]string{
	MessageCauseCommandNotFound:      "command not found locally",
	MessageConsequenceCommandRejects: "the shell would reject this command",
	MessageCauseUnknownGitSubcommand: "unknown Git subcommand",
	MessageConsequenceGitExits:       "Git will exit before performing work",
	MessageCausePathNotFound:         "path does not exist",
	MessageConsequencePathMayFail:    "the command may fail or target the wrong file",
	MessageRiskSecret:                "contains a secret-bearing argument",
	MessageRiskPrivilegeEscalation:   "invokes privilege escalation",
	MessageRiskNetworkEffect:         "has a network effect",
	MessageRiskFilesystemMutation:    "may modify the filesystem",
	MessageRiskRecognizedSafe:        "is a recognized read-only command",
	MessageRiskUnknown:               "could not establish a safe local classification",
}

var consequenceTemplates = map[RepairClass]consequenceTemplate{
	RepairClassCommand:  {cause: MessageCauseCommandNotFound, consequence: MessageConsequenceCommandRejects},
	RepairClassSemantic: {cause: MessageCauseUnknownGitSubcommand, consequence: MessageConsequenceGitExits},
	RepairClassPath:     {cause: MessageCausePathNotFound, consequence: MessageConsequencePathMayFail},
}

func DefaultMessage(key MessageKey) (string, bool) {
	value, ok := defaultMessages[key]
	return value, ok
}

type Decision struct {
	Version          int         `json:"version"`
	Action           string      `json:"action"`
	RewriteEligible  bool        `json:"rewrite_eligible"`
	Cause            string      `json:"cause,omitempty"`
	CauseKey         MessageKey  `json:"cause_key,omitempty"`
	Consequence      string      `json:"consequence,omitempty"`
	ConsequenceKey   MessageKey  `json:"consequence_key,omitempty"`
	Suggestion       string      `json:"suggestion,omitempty"`
	Class            RepairClass `json:"class,omitempty"`
	Evidence         []Evidence  `json:"evidence,omitempty"`
	Confidence       float64     `json:"confidence"`
	Risk             Risk        `json:"risk"`
	RiskRationale    string      `json:"risk_rationale,omitempty"`
	RiskRationaleKey MessageKey  `json:"risk_rationale_key,omitempty"`
	Incomplete       bool        `json:"incomplete,omitempty"`
	Trace            []string    `json:"trace,omitempty"`
	original         string
	replacement      string
	occurrence       int
}

type Event struct {
	Version          int         `json:"version"`
	Stage            string      `json:"stage"`
	Action           string      `json:"action"`
	RewriteEligible  bool        `json:"rewrite_eligible"`
	Cause            string      `json:"cause,omitempty"`
	CauseKey         MessageKey  `json:"cause_key,omitempty"`
	Consequence      string      `json:"consequence,omitempty"`
	ConsequenceKey   MessageKey  `json:"consequence_key,omitempty"`
	Suggestion       string      `json:"suggestion,omitempty"`
	Class            RepairClass `json:"class,omitempty"`
	Evidence         []Evidence  `json:"evidence,omitempty"`
	Confidence       float64     `json:"confidence"`
	Risk             Risk        `json:"risk"`
	RiskRationale    string      `json:"risk_rationale,omitempty"`
	RiskRationaleKey MessageKey  `json:"risk_rationale_key,omitempty"`
	Incomplete       bool        `json:"incomplete,omitempty"`
	Trace            []string    `json:"trace,omitempty"`
}

type Inspection struct {
	Event
	Diff           string `json:"diff,omitempty"`
	EmphasizedDiff string `json:"emphasized_diff,omitempty"`
}

func (d Decision) Event(stage string) Event {
	return Event{Version: d.Version, Stage: stage, Action: d.Action, RewriteEligible: d.RewriteEligible, Cause: d.Cause, CauseKey: d.CauseKey, Consequence: d.Consequence, ConsequenceKey: d.ConsequenceKey, Suggestion: d.Suggestion, Class: d.Class, Evidence: append([]Evidence(nil), d.Evidence...), Confidence: d.Confidence, Risk: d.Risk, RiskRationale: d.RiskRationale, RiskRationaleKey: d.RiskRationaleKey, Incomplete: d.Incomplete, Trace: append([]string(nil), d.Trace...)}
}

func (d Decision) Inspect(stage, command string) (Inspection, error) {
	if stage != "pre" && stage != "post" {
		return Inspection{}, fmt.Errorf("invalid inspection stage %q", stage)
	}
	if err := d.validateProtocol(); err != nil {
		return Inspection{}, err
	}
	return Inspection{Event: d.Event(stage), Diff: d.CommandDiff(command), EmphasizedDiff: d.CommandDiffEmphasis(command)}, nil
}

func (d Decision) Record() (string, error) {
	if err := d.validateProtocol(); err != nil {
		return "", err
	}
	fields := []string{strconv.Itoa(d.Version), d.Action, string(d.Risk), fmt.Sprintf("%.2f", d.Confidence), encodeRecordText(d.Cause), encodeRecordText(d.Consequence), encodeRecordText(d.Suggestion)}
	record := strings.Join(fields, "\t") + "\n"
	if len(record) > MaxOutputBytes {
		return "", ErrOutputLimit
	}
	return record, nil
}

func (d Decision) JSON(stage string) ([]byte, error) {
	if stage != "pre" && stage != "post" {
		return nil, fmt.Errorf("invalid JSON stage %q", stage)
	}
	if err := d.validateProtocol(); err != nil {
		return nil, err
	}
	data, err := json.Marshal(d.Event(stage))
	if err != nil {
		return nil, err
	}
	if len(data)+1 > MaxOutputBytes {
		return nil, ErrOutputLimit
	}
	return data, nil
}

func (d Decision) validateProtocol() error {
	if d.Version != AdapterProtocolVersion {
		return fmt.Errorf("unsupported protocol version %d", d.Version)
	}
	if !validAction(d.Action) {
		return fmt.Errorf("invalid protocol action %q", d.Action)
	}
	if !validRisk(d.Risk) {
		return fmt.Errorf("invalid protocol risk %q", d.Risk)
	}
	if math.IsNaN(d.Confidence) || math.IsInf(d.Confidence, 0) || d.Confidence < 0 || d.Confidence > 1 {
		return fmt.Errorf("invalid protocol confidence %v", d.Confidence)
	}
	return nil
}

func encodeRecordText(value string) string {
	return base64.RawStdEncoding.EncodeToString([]byte(value))
}

func validAction(value string) bool {
	return value == "none" || value == "hint" || value == "interrupt" || value == "rewrite"
}

func validRisk(value Risk) bool {
	return value == RiskSafe || value == RiskUnknown || value == RiskHigh
}

type Options struct {
	Config           config.Config
	Path             string
	CWD              string
	SemanticResolver SemanticResolver
	Limits           Limits
	Clock            func() time.Time
	Cache            *Cache
}

type SemanticMatch struct {
	PackID      string
	RuleID      string
	Source      string
	Suggestion  string
	Cause       string
	Risk        Risk
	Rationale   string
	Original    string
	Replacement string
	Occurrence  int
}

type SemanticResolver interface {
	MatchWordsContext(context.Context, []string) (SemanticMatch, bool, error)
}

type Limits struct {
	InputBytes   int
	OutputBytes  int
	AnalysisTime time.Duration
}

type Engine struct {
	options Options
	cache   *Cache
}

type executableCacheEntry struct {
	signature string
	names     []string
}

type Cache struct {
	sync.RWMutex
	entries map[string]executableCacheEntry
}

var defaultExecutableCache = NewCache()

func NewCache() *Cache { return &Cache{entries: map[string]executableCacheEntry{}} }

func New(options Options) Engine {
	cache := options.Cache
	if cache == nil {
		cache = NewCache()
	}
	return Engine{options: options, cache: cache}
}

func (e Engine) InvalidateCache() { e.cache.Invalidate() }

func (e Engine) Close() { e.InvalidateCache() }

func (c *Cache) Invalidate() {
	c.Lock()
	c.entries = map[string]executableCacheEntry{}
	c.Unlock()
}

func (e Engine) Check(line, stage string) (Decision, error) {
	return e.CheckContext(context.Background(), line, stage)
}

func (e Engine) CheckContext(ctx context.Context, line, stage string) (Decision, error) {
	return e.CheckShellContext(ctx, "", line, stage)
}

func (e Engine) CheckShell(shellName, line, stage string) (Decision, error) {
	return e.CheckShellContext(context.Background(), shellName, line, stage)
}

func (e Engine) CheckShellContext(ctx context.Context, shellName, line, stage string) (Decision, error) {
	if e.cache == nil {
		e.cache = NewCache()
	}
	if err := ctx.Err(); err != nil {
		return noDecision(), err
	}
	limits := e.limits()
	if len(line) > limits.InputBytes {
		return noDecision(), ErrInputLimit
	}
	if e.options.Config.HasRuleException(line) {
		return noDecision(), nil
	}
	started := e.now()
	words, err := tokenizeForShell(shellName, line)
	if err != nil {
		decision := noDecision()
		decision.Incomplete = errors.Is(err, errIncompleteShellInput)
		return decision, nil
	}
	if err := ctx.Err(); err != nil {
		return noDecision(), err
	}
	if len(words) == 0 || e.options.Config.Mode == "off" {
		return noDecision(), nil
	}
	if hasUnsupportedShellSyntax(words) {
		return noDecision(), nil
	}
	if decision, err := e.commandDecision(ctx, words); err != nil {
		return noDecision(), err
	} else if decision.Suggestion != "" {
		return e.finish(ctx, decision, shellName, line, stage, started, limits)
	}
	if decision, err := e.semanticDecision(ctx, shellName, words); err != nil {
		return noDecision(), err
	} else if decision.Suggestion != "" {
		return e.finish(ctx, decision, shellName, line, stage, started, limits)
	}
	if decision, err := e.pathDecision(ctx, words); err != nil {
		return noDecision(), err
	} else if decision.Suggestion != "" {
		return e.finish(ctx, decision, shellName, line, stage, started, limits)
	}
	if err := ctx.Err(); err != nil {
		return noDecision(), err
	}
	if e.now().Sub(started) > limits.AnalysisTime {
		return noDecision(), ErrAnalysisLimit
	}
	return noDecision(), nil
}

func (e Engine) limits() Limits {
	limits := e.options.Limits
	if limits.InputBytes <= 0 {
		limits.InputBytes = MaxInputBytes
	}
	if limits.OutputBytes <= 0 {
		limits.OutputBytes = MaxOutputBytes
	}
	if limits.AnalysisTime <= 0 {
		limits.AnalysisTime = MaxAnalysisDuration
	}
	return limits
}

func (e Engine) now() time.Time {
	if e.options.Clock != nil {
		return e.options.Clock()
	}
	return time.Now()
}

func (e Engine) finish(ctx context.Context, decision Decision, shellName, line, stage string, started time.Time, limits Limits) (Decision, error) {
	if err := ctx.Err(); err != nil {
		return noDecision(), err
	}
	if e.now().Sub(started) > limits.AnalysisTime {
		return noDecision(), ErrAnalysisLimit
	}
	if decisionOutputSize(decision) > limits.OutputBytes {
		return noDecision(), ErrOutputLimit
	}
	decision = e.applyMode(decision, stage)
	if decision.Action == "rewrite" && !rewriteCompatible(shellName, line) {
		decision.Action = "hint"
	}
	if decision.Action == "rewrite" && decision.original != "" && decision.replacement != "" {
		buffer, ok := replaceTokenOccurrence(line, decision.original, decision.replacement, decision.occurrence)
		if !ok {
			return noDecision(), nil
		}
		decision.Suggestion = buffer
		if decisionOutputSize(decision) > limits.OutputBytes {
			return noDecision(), ErrOutputLimit
		}
	}
	return decision, nil
}

func decisionOutputSize(decision Decision) int {
	size := len(decision.Cause) + len(decision.CauseKey) + len(decision.Consequence) + len(decision.ConsequenceKey) + len(decision.Suggestion) + len(decision.Class) + len(decision.Risk) + len(decision.RiskRationale) + len(decision.RiskRationaleKey) + 128
	for _, evidence := range decision.Evidence {
		size += len(evidence.Kind) + len(evidence.Value)
	}
	for _, trace := range decision.Trace {
		size += len(trace)
	}
	return size
}

func noDecision() Decision {
	return Decision{Version: AdapterProtocolVersion, Action: "none", Risk: RiskSafe}
}

func consequenceFor(class RepairClass) (consequenceTemplate, bool) {
	template, ok := consequenceTemplates[class]
	return template, ok
}

func (e Engine) applyMode(decision Decision, stage string) Decision {
	decision.RewriteEligible = intrinsicRewriteEligible(decision)
	if stage == "pre" {
		if rewritten, ok := e.evaluateRewriteBuffer(decision); ok {
			return rewritten
		}
	}
	if e.shouldInterrupt(decision, stage) {
		decision.Action = "interrupt"
		return decision
	}
	decision.Action = "hint"
	return decision
}

func (e Engine) safeAutoApply(decision Decision) bool {
	return e.options.Config.Mode == "rewrite" &&
		e.options.Config.AutoApplySafe &&
		intrinsicRewriteEligible(decision)
}

func intrinsicRewriteEligible(decision Decision) bool {
	return decision.Suggestion != "" &&
		!decision.Incomplete &&
		decision.Risk == RiskSafe &&
		decision.Confidence >= 0.80 &&
		meetsConfidenceThreshold(decision.Class, decision.Confidence) &&
		semanticRewriteAllowed(decision)
}

func semanticRewriteAllowed(decision Decision) bool {
	if decision.Class != RepairClassSemantic {
		return true
	}
	for _, evidence := range decision.Evidence {
		if evidence.Kind == "source" && evidence.Value == "installed" {
			return false
		}
	}
	return true
}

func (e Engine) evaluateRewriteBuffer(decision Decision) (Decision, bool) {
	if !e.safeAutoApply(decision) {
		return decision, false
	}
	decision.Action = "rewrite"
	return decision, true
}

func (e Engine) shouldInterrupt(decision Decision, stage string) bool {
	return stage == "pre" &&
		(e.options.Config.Mode == "interrupt" || e.options.Config.Mode == "rewrite" && e.options.Config.RiskInterrupt) &&
		decision.Suggestion != "" &&
		!decision.Incomplete &&
		decision.Confidence >= 0.90 &&
		meetsConfidenceThreshold(decision.Class, decision.Confidence)
}

func (e Engine) commandDecision(ctx context.Context, words []string) (Decision, error) {
	if err := ctx.Err(); err != nil {
		return Decision{}, err
	}
	candidates := e.cache.executableNamesFor(e.options.Path, runtime.GOOS, os.Getenv("PATHEXT"))
	if err := ctx.Err(); err != nil {
		return Decision{}, err
	}
	for _, position := range commandPositions(words) {
		if err := ctx.Err(); err != nil {
			return Decision{}, err
		}
		word := words[position]
		if isPathQualified(word, runtime.GOOS) || e.cache.commandExistsFor(word, e.options.Path, runtime.GOOS, os.Getenv("PATHEXT")) {
			continue
		}
		best, distance := nearest(word, candidates)
		if best == "" || distance > maxDistance(word) {
			continue
		}
		confidence := confidence(word, best)
		if !meetsConfidenceThreshold(RepairClassCommand, confidence) {
			continue
		}
		replaced := append([]string{}, words...)
		replaced[position] = best
		suggestion, containsSecret := redact.Command(replaced)
		template, _ := consequenceFor(RepairClassCommand)
		assessment := assessRisk(replaced, containsSecret)
		return Decision{Version: AdapterProtocolVersion, Cause: defaultMessages[template.cause], CauseKey: template.cause, Consequence: defaultMessages[template.consequence], ConsequenceKey: template.consequence, Suggestion: suggestion, Class: RepairClassCommand, Evidence: collectEvidence(RepairClassCommand, "path", distance, confidence), Confidence: confidence, Risk: assessment.risk, RiskRationale: defaultMessages[assessment.rationale], RiskRationaleKey: assessment.rationale, Trace: []string{"resolver:path", "distance:" + fmt.Sprint(distance)}, original: word, replacement: best, occurrence: tokenOccurrence(words, position)}, nil
	}
	return Decision{}, nil
}

func (e Engine) semanticDecision(ctx context.Context, shellName string, words []string) (Decision, error) {
	if err := ctx.Err(); err != nil {
		return Decision{}, err
	}
	if e.options.SemanticResolver == nil {
		return Decision{}, nil
	}
	match, ok, err := e.options.SemanticResolver.MatchWordsContext(ctx, words)
	if err != nil {
		return Decision{}, err
	}
	if err := ctx.Err(); err != nil {
		return Decision{}, err
	}
	if !ok || match.PackID == "" || match.RuleID == "" || match.Suggestion == "" || !validRisk(match.Risk) {
		return Decision{}, nil
	}
	suggestedWords, err := tokenizeForShell(shellName, match.Suggestion)
	if err != nil || len(suggestedWords) == 0 || hasUnsupportedShellSyntax(suggestedWords) {
		return Decision{}, nil
	}
	suggestion, containsSecret := redact.Command(suggestedWords)
	risk, rationale, rationaleKey := match.Risk, match.Rationale, MessageKey("")
	if containsSecret {
		risk = RiskHigh
		rationale = defaultMessages[MessageRiskSecret]
		rationaleKey = MessageRiskSecret
	}
	evidence := []Evidence{{Kind: "resolver", Value: "curated"}, {Kind: "pack", Value: match.PackID}, {Kind: "rule", Value: match.RuleID}}
	if match.Source != "" {
		evidence = append(evidence, Evidence{Kind: "source", Value: match.Source})
	}
	return Decision{Version: AdapterProtocolVersion, Cause: match.Cause, Suggestion: suggestion, Class: RepairClassSemantic, Evidence: evidence, Confidence: 1, Risk: risk, RiskRationale: rationale, RiskRationaleKey: rationaleKey, Trace: []string{"pack:" + match.PackID, "rule:" + match.RuleID}, original: match.Original, replacement: match.Replacement, occurrence: match.Occurrence}, nil
}

func (e Engine) pathDecision(ctx context.Context, words []string) (Decision, error) {
	for i := 1; i < len(words); i++ {
		if err := ctx.Err(); err != nil {
			return Decision{}, err
		}
		word := words[i]
		if strings.HasPrefix(word, "-") || !strings.Contains(word, "/") && !strings.HasPrefix(word, ".") {
			continue
		}
		if _, err := os.Stat(filepath.Join(e.options.CWD, word)); err == nil {
			continue
		}
		dir, base := filepath.Split(word)
		entries, err := limitedReadDir(filepath.Join(e.options.CWD, dir))
		if err != nil {
			continue
		}
		names := make([]string, 0, len(entries))
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
		best, distance := nearest(base, names)
		if best == "" || distance > maxDistance(base) {
			continue
		}
		confidence := confidence(base, best)
		if !meetsConfidenceThreshold(RepairClassPath, confidence) {
			continue
		}
		replaced := append([]string{}, words...)
		replacement := filepath.Join(dir, best)
		replaced[i] = replacement
		suggestion, containsSecret := redact.Command(replaced)
		template, _ := consequenceFor(RepairClassPath)
		assessment := assessRisk(replaced, containsSecret)
		return Decision{Version: AdapterProtocolVersion, Cause: defaultMessages[template.cause], CauseKey: template.cause, Consequence: defaultMessages[template.consequence], ConsequenceKey: template.consequence, Suggestion: suggestion, Class: RepairClassPath, Evidence: collectEvidence(RepairClassPath, "filesystem", distance, confidence), Confidence: confidence, Risk: assessment.risk, RiskRationale: defaultMessages[assessment.rationale], RiskRationaleKey: assessment.rationale, Trace: []string{"resolver:filesystem", "distance:" + fmt.Sprint(distance)}, original: word, replacement: replacement, occurrence: tokenOccurrence(words, i)}, nil
	}
	return Decision{}, nil
}

func tokenize(line string) ([]string, error) {
	var result []string
	var current strings.Builder
	var quote rune
	escaped := false
	wordStarted := false
	flush := func() {
		if wordStarted {
			result = append(result, current.String())
			current.Reset()
			wordStarted = false
		}
	}
	runes := []rune(line)
	for index := 0; index < len(runes); index++ {
		r := runes[index]
		if escaped {
			current.WriteRune(r)
			escaped = false
			wordStarted = true
			continue
		}
		if r == '\\' && quote != '\'' {
			escaped = true
			wordStarted = true
			continue
		}
		if quote != 0 {
			if r == quote {
				quote = 0
			} else {
				current.WriteRune(r)
			}
			wordStarted = true
			continue
		}
		if r == '\'' || r == '"' {
			quote = r
			wordStarted = true
			continue
		}
		if operator, width := compoundOperator(runes[index:]); width > 0 {
			flush()
			result = append(result, operator)
			index += width - 1
			continue
		}
		if r == ' ' || r == '\t' {
			flush()
			continue
		}
		current.WriteRune(r)
		wordStarted = true
	}
	if escaped || quote != 0 {
		return nil, errIncompleteShellInput
	}
	flush()
	return result, nil
}

var (
	errIncompleteShellInput   = errors.New("incomplete shell input")
	errUnsupportedShellSyntax = errors.New("unsupported shell syntax")
)

type shellLexer int

const (
	shellPOSIX shellLexer = iota
	shellFish
	shellPowerShell
)

// ShellCommandSupported reports whether line is simple enough to analyze without
// changing its shell semantics. Unknown shells are intentionally not analyzed.
func ShellCommandSupported(shellName, line string) bool {
	words, err := tokenizeForShell(shellName, line)
	return err == nil && !hasUnsupportedShellSyntax(words)
}

func tokenizeForShell(shellName, line string) ([]string, error) {
	switch strings.ToLower(strings.TrimSpace(shellName)) {
	case "":
		return tokenize(line)
	case "bash", "zsh":
		return tokenizeConservative(line, shellPOSIX, shellName)
	case "fish":
		return tokenizeConservative(line, shellFish, shellName)
	case "powershell", "pwsh":
		return tokenizeConservative(line, shellPowerShell, shellName)
	default:
		return nil, errUnsupportedShellSyntax
	}
}

func tokenizeConservative(line string, lexer shellLexer, shellName string) ([]string, error) {
	var result []string
	var current strings.Builder
	var quote rune
	wordStarted := false
	runes := []rune(line)
	flush := func() {
		if wordStarted {
			result = append(result, current.String())
			current.Reset()
			wordStarted = false
		}
	}
	for index := 0; index < len(runes); index++ {
		character := runes[index]
		if quote != 0 {
			if quote == '\'' && lexer == shellPowerShell && character == '\'' && index+1 < len(runes) && runes[index+1] == '\'' {
				current.WriteRune(character)
				wordStarted = true
				index++
				continue
			}
			if character == quote {
				quote = 0
				continue
			}
			if quote == '"' && character == '\\' && lexer != shellPowerShell {
				if index+1 == len(runes) {
					return nil, errIncompleteShellInput
				}
				next := runes[index+1]
				if lexer == shellPOSIX && !strings.ContainsRune("$`\\\"\n", next) {
					current.WriteRune(character)
				}
				if next != '\n' {
					current.WriteRune(next)
				}
				wordStarted = true
				index++
				continue
			}
			if character == '`' || quote == '"' && character == '$' {
				return nil, errUnsupportedShellSyntax
			}
			current.WriteRune(character)
			wordStarted = true
			continue
		}
		if character == ' ' || character == '\t' {
			flush()
			continue
		}
		if character == '\'' || character == '"' {
			quote = character
			wordStarted = true
			continue
		}
		if character == '\\' && lexer != shellPowerShell {
			if index+1 == len(runes) {
				return nil, errIncompleteShellInput
			}
			next := runes[index+1]
			if next != '\n' {
				current.WriteRune(next)
			}
			wordStarted = true
			index++
			continue
		}
		if unsafeShellCharacter(character, lexer, shellName, !wordStarted) {
			return nil, errUnsupportedShellSyntax
		}
		current.WriteRune(character)
		wordStarted = true
	}
	if quote != 0 {
		return nil, errIncompleteShellInput
	}
	flush()
	if hasUnsupportedShellSyntax(result) {
		return nil, errUnsupportedShellSyntax
	}
	return result, nil
}

func unsafeShellCharacter(character rune, lexer shellLexer, shellName string, startsWord bool) bool {
	if strings.ContainsRune(";|&()<>$*?[]{}\n#`", character) {
		return true
	}
	if lexer == shellPowerShell && (character == '@' || character == ',') {
		return true
	}
	return (lexer == shellPOSIX && strings.EqualFold(shellName, "zsh") && character == '!') || (startsWord && character == '~')
}

func rewriteCompatible(shellName, line string) bool {
	return shellName == "" || !strings.ContainsAny(line, "'\\\"\\\\")
}

func tokenOccurrence(words []string, position int) int {
	occurrence := 0
	for index := 0; index <= position; index++ {
		if words[index] == words[position] {
			occurrence++
		}
	}
	return occurrence
}

func (d Decision) CommandDiff(line string) string {
	if d.Risk == RiskHigh || d.original == "" || d.replacement == "" || d.occurrence < 1 {
		return ""
	}
	words, err := tokenize(line)
	if err != nil {
		return ""
	}
	if _, containsSecret := redact.Command(words); containsSecret {
		return ""
	}
	corrected, ok := replaceTokenOccurrence(line, d.original, d.replacement, d.occurrence)
	if !ok {
		return ""
	}
	return "- " + line + "\n+ " + corrected
}

func (d Decision) CommandDiffEmphasis(line string) string {
	if d.Risk == RiskHigh || d.original == "" || d.replacement == "" || d.occurrence < 1 {
		return ""
	}
	words, err := tokenize(line)
	if err != nil {
		return ""
	}
	if _, containsSecret := redact.Command(words); containsSecret {
		return ""
	}
	matched := 0
	for _, token := range shellTokenRanges(line) {
		if token.value != d.original {
			continue
		}
		matched++
		if matched != d.occurrence {
			continue
		}
		replacement := quotedReplacement(line[token.start:token.end], d.replacement)
		return line[:token.start] + "[-" + line[token.start:token.end] + "-]{+" + replacement + "+}" + line[token.end:]
	}
	return ""
}

type shellTokenRange struct {
	start int
	end   int
	value string
}

func replaceTokenOccurrence(line, original, replacement string, occurrence int) (string, bool) {
	matched := 0
	for _, token := range shellTokenRanges(line) {
		if token.value != original {
			continue
		}
		matched++
		if matched != occurrence {
			continue
		}
		return line[:token.start] + quotedReplacement(line[token.start:token.end], replacement) + line[token.end:], true
	}
	return "", false
}

func shellTokenRanges(line string) []shellTokenRange {
	ranges := []shellTokenRange{}
	var value strings.Builder
	start := -1
	var quote rune
	escaped := false
	flush := func(end int) {
		if start >= 0 {
			ranges = append(ranges, shellTokenRange{start: start, end: end, value: value.String()})
			value.Reset()
			start = -1
		}
	}
	for index, character := range line {
		if escaped {
			value.WriteRune(character)
			escaped = false
			continue
		}
		if character == '\\' && quote != '\'' {
			if start < 0 {
				start = index
			}
			escaped = true
			continue
		}
		if quote != 0 {
			if character == quote {
				quote = 0
			} else {
				value.WriteRune(character)
			}
			continue
		}
		if character == '\'' || character == '"' {
			if start < 0 {
				start = index
			}
			quote = character
			continue
		}
		if character == ' ' || character == '\t' {
			flush(index)
			continue
		}
		if character == ';' || character == '&' || character == '|' || character == '(' || character == ')' || character == '\n' {
			flush(index)
			continue
		}
		if start < 0 {
			start = index
		}
		value.WriteRune(character)
	}
	flush(len(line))
	return ranges
}

func quotedReplacement(raw, replacement string) string {
	if len(raw) >= 2 && raw[0] == '\'' && raw[len(raw)-1] == '\'' {
		return "'" + strings.ReplaceAll(replacement, "'", "'\\''") + "'"
	}
	if len(raw) >= 2 && raw[0] == '"' && raw[len(raw)-1] == '"' {
		return `"` + strings.NewReplacer("\\", "\\\\", "\"", "\\\"", "$", "\\$", "`", "\\`").Replace(replacement) + `"`
	}
	return replacement
}

func compoundOperator(runes []rune) (string, int) {
	if len(runes) == 0 {
		return "", 0
	}
	switch runes[0] {
	case ';', '(', ')':
		return string(runes[0]), 1
	case '&':
		if len(runes) > 1 && runes[1] == '&' {
			return "&&", 2
		}
		return "&", 1
	case '|':
		if len(runes) > 1 && (runes[1] == '|' || runes[1] == '&') {
			return string(runes[:2]), 2
		}
		return "|", 1
	case '\n':
		return ";", 1
	default:
		return "", 0
	}
}

func commandPositions(words []string) []int {
	positions := []int{}
	expectCommand := true
	for index, word := range words {
		if isCompoundOperator(word) {
			expectCommand = word != ")"
			continue
		}
		if !expectCommand {
			continue
		}
		if isShellKeyword(word) || assignmentWord(word) {
			continue
		}
		positions = append(positions, index)
		expectCommand = false
	}
	return positions
}

func isCompoundOperator(value string) bool {
	return value == ";" || value == "&" || value == "&&" || value == "|" || value == "|&" || value == "||" || value == "(" || value == ")"
}

func hasUnsupportedShellSyntax(words []string) bool {
	for _, word := range words {
		if isCompoundOperator(word) || strings.ContainsAny(word, "<>`$*?[]{}") {
			return true
		}
	}
	return false
}

func assignmentWord(value string) bool {
	name, _, found := strings.Cut(value, "=")
	if !found || name == "" {
		return false
	}
	for index, character := range name {
		if character == '_' || character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || index > 0 && character >= '0' && character <= '9' {
			continue
		}
		return false
	}
	return true
}

func executableNames(pathValue string) []string {
	return defaultExecutableCache.executableNamesFor(pathValue, runtime.GOOS, os.Getenv("PATHEXT"))
}

func executableNamesFor(pathValue, platform, pathExt string) []string {
	return defaultExecutableCache.executableNamesFor(pathValue, platform, pathExt)
}

func (c *Cache) executableNamesFor(pathValue, platform, pathExt string) []string {
	cacheKey := platform + "\x00" + pathExt + "\x00" + pathValue
	signature := pathSignature(pathValue)
	c.RLock()
	entry, ok := c.entries[cacheKey]
	c.RUnlock()
	if ok && entry.signature == signature {
		return append([]string(nil), entry.names...)
	}
	seen := map[string]struct{}{}
	for index, dir := range filepath.SplitList(pathValue) {
		if index >= maxPathDirectories {
			break
		}
		entries, err := limitedReadDir(dir)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			info, err := entry.Info()
			if err == nil && isExecutableCandidate(entry.Name(), info.Mode(), platform, pathExt) {
				seen[normalizeExecutableName(entry.Name(), platform, pathExt)] = struct{}{}
			}
		}
	}
	result := make([]string, 0, len(seen))
	for name := range seen {
		result = append(result, name)
	}
	sort.Strings(result)
	c.Lock()
	c.entries[cacheKey] = executableCacheEntry{signature: signature, names: append([]string(nil), result...)}
	c.Unlock()
	return result
}

func limitedReadDir(path string) ([]os.DirEntry, error) {
	// #nosec G304,G703 -- PATH is intentionally inspected after runtime validation rejects unsafe entries.
	directory, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer directory.Close()
	entries, err := directory.ReadDir(maxDirectoryEntries)
	if errors.Is(err, io.EOF) {
		return entries, nil
	}
	return entries, err
}

func commandExistsFor(name, pathValue, platform, pathExt string) bool {
	return defaultExecutableCache.commandExistsFor(name, pathValue, platform, pathExt)
}

func (c *Cache) commandExistsFor(name, pathValue, platform, pathExt string) bool {
	if platform != "windows" {
		for index, dir := range filepath.SplitList(pathValue) {
			if index >= maxPathDirectories {
				break
			}
			// #nosec G703 -- PATH is intentionally inspected after runtime validation rejects unsafe entries.
			info, err := os.Stat(filepath.Join(dir, name))
			if err == nil && !info.IsDir() && info.Mode()&0o111 != 0 {
				return true
			}
		}
		return false
	}
	names := c.executableNamesFor(pathValue, platform, pathExt)
	name = normalizeExecutableName(name, platform, pathExt)
	index := sort.SearchStrings(names, name)
	return index < len(names) && names[index] == name
}

func InvalidateExecutableIndex() {
	defaultExecutableCache.Invalidate()
}

func pathSignature(pathValue string) string {
	var signature strings.Builder
	for index, dir := range filepath.SplitList(pathValue) {
		if index >= maxPathDirectories {
			signature.WriteString("truncated\x00")
			break
		}
		// #nosec G703 -- PATH is intentionally inspected after runtime validation rejects unsafe entries.
		info, err := os.Stat(dir)
		if err != nil {
			signature.WriteString(dir)
			signature.WriteString(":missing\x00")
			continue
		}
		signature.WriteString(dir)
		signature.WriteByte(':')
		signature.WriteString(strconv.FormatInt(info.ModTime().UnixNano(), 10))
		signature.WriteByte(':')
		signature.WriteString(strconv.FormatInt(info.Size(), 10))
		signature.WriteByte('\x00')
	}
	return signature.String()
}

func isExecutableCandidate(name string, mode os.FileMode, platform, pathExt string) bool {
	if platform != "windows" {
		return mode&0o111 != 0
	}
	_, ok := executableExtension(name, pathExt)
	return ok
}

func normalizeExecutableName(name, platform, pathExt string) string {
	if platform != "windows" {
		return name
	}
	if extension, ok := executableExtension(name, pathExt); ok {
		name = name[:len(name)-len(extension)]
	}
	return strings.ToLower(name)
}

func executableExtension(name, pathExt string) (string, bool) {
	lowerName := strings.ToLower(name)
	for _, extension := range executableExtensions(pathExt) {
		if strings.HasSuffix(lowerName, extension) {
			return extension, true
		}
	}
	return "", false
}

func executableExtensions(pathExt string) []string {
	if pathExt == "" {
		pathExt = ".COM;.EXE;.BAT;.CMD"
	}
	extensions := []string{}
	for _, extension := range strings.Split(pathExt, ";") {
		extension = strings.TrimSpace(extension)
		if extension == "" {
			continue
		}
		if !strings.HasPrefix(extension, ".") {
			extension = "." + extension
		}
		extensions = append(extensions, strings.ToLower(extension))
	}
	return extensions
}

func isPathQualified(value, platform string) bool {
	if platform == "windows" {
		return strings.ContainsAny(value, "/\\")
	}
	return strings.Contains(value, "/")
}

func nearest(value string, candidates []string) (string, int) {
	ranked := rankCandidates(value, candidates)
	if len(ranked) == 0 {
		return "", 0
	}
	return ranked[0].value, ranked[0].editDistance
}

type rankedCandidate struct {
	value            string
	editDistance     int
	keyboardDistance int
}

func rankCandidates(value string, candidates []string) []rankedCandidate {
	seen := map[string]struct{}{}
	ranked := make([]rankedCandidate, 0, len(candidates))
	for _, candidate := range candidates {
		if _, exists := seen[candidate]; exists {
			continue
		}
		seen[candidate] = struct{}{}
		ranked = append(ranked, rankedCandidate{value: candidate, editDistance: damerauLevenshtein(value, candidate), keyboardDistance: keyboardAdjacencyDistance(value, candidate)})
	}
	sort.Slice(ranked, func(left, right int) bool {
		if ranked[left].editDistance != ranked[right].editDistance {
			return ranked[left].editDistance < ranked[right].editDistance
		}
		if ranked[left].keyboardDistance != ranked[right].keyboardDistance {
			return ranked[left].keyboardDistance < ranked[right].keyboardDistance
		}
		return ranked[left].value < ranked[right].value
	})
	return ranked
}

var keyboardRows = [][]rune{
	[]rune("1234567890-="),
	[]rune("qwertyuiop[]\\"),
	[]rune("asdfghjkl;'"),
	[]rune("zxcvbnm,./"),
}

func keyboardAdjacencyDistance(a, b string) int {
	aRunes, bRunes := []rune(strings.ToLower(a)), []rune(strings.ToLower(b))
	previous := make([]int, len(bRunes)+1)
	for index := range previous {
		previous[index] = index * 2
	}
	for row, left := range aRunes {
		current := make([]int, len(bRunes)+1)
		current[0] = (row + 1) * 2
		for column, right := range bRunes {
			substitution := 2
			if left == right {
				substitution = 0
			} else if keyboardAdjacent(left, right) {
				substitution = 1
			}
			current[column+1] = min(current[column]+2, previous[column+1]+2, previous[column]+substitution)
		}
		previous = current
	}
	return previous[len(bRunes)]
}

func keyboardAdjacent(left, right rune) bool {
	left, right = unicode.ToLower(left), unicode.ToLower(right)
	for leftRow, keys := range keyboardRows {
		for leftColumn, key := range keys {
			if key != left {
				continue
			}
			for rightRow, rightKeys := range keyboardRows {
				for rightColumn, rightKey := range rightKeys {
					if rightKey == right && abs(leftRow-rightRow) <= 1 && abs(leftColumn-rightColumn) <= 1 {
						return true
					}
				}
			}
		}
	}
	return false
}

func abs(value int) int {
	if value < 0 {
		return -value
	}
	return value
}

func damerauLevenshtein(a, b string) int {
	aRunes, bRunes := []rune(a), []rune(b)
	previousPrevious := make([]int, len(bRunes)+1)
	previous := make([]int, len(bRunes)+1)
	for j := range previous {
		previous[j] = j
	}
	for i, ra := range aRunes {
		current := make([]int, len(bRunes)+1)
		current[0] = i + 1
		for j, rb := range bRunes {
			cost := 0
			if ra != rb {
				cost = 1
			}
			current[j+1] = min(current[j]+1, previous[j+1]+1, previous[j]+cost)
			if i > 0 && j > 0 && ra == bRunes[j-1] && aRunes[i-1] == rb {
				current[j+1] = min(current[j+1], previousPrevious[j-1]+1)
			}
		}
		previousPrevious, previous = previous, current
	}
	return previous[len(bRunes)]
}

func min(values ...int) int {
	result := values[0]
	for _, value := range values[1:] {
		if value < result {
			result = value
		}
	}
	return result
}
func maxDistance(value string) int {
	length := len([]rune(value))
	if length <= 4 {
		return 1
	}
	if length <= 8 {
		return 2
	}
	return 3
}
func confidence(a, b string) float64 {
	return 1 - float64(damerauLevenshtein(a, b))/float64(max(len([]rune(a)), len([]rune(b))))
}
func meetsConfidenceThreshold(class RepairClass, value float64) bool {
	return isKnownRepairClass(class) && value >= confidenceThreshold(class)
}
func isKnownRepairClass(class RepairClass) bool {
	switch class {
	case RepairClassCommand, RepairClassSemantic, RepairClassPath:
		return true
	default:
		return false
	}
}
func confidenceThreshold(class RepairClass) float64 {
	switch class {
	case RepairClassCommand:
		return 0.60
	case RepairClassSemantic:
		return 0.75
	case RepairClassPath:
		return 0.90
	default:
		return 1
	}
}
func collectEvidence(class RepairClass, resolver string, distance int, value float64) []Evidence {
	if resolver == "" || distance < 0 || !meetsConfidenceThreshold(class, value) {
		return nil
	}
	return []Evidence{
		{Kind: "resolver", Value: resolver},
		{Kind: "edit_distance", Value: strconv.Itoa(distance)},
		{Kind: "confidence_threshold", Value: fmt.Sprintf("%.2f", confidenceThreshold(class))},
	}
}
func isShellKeyword(value string) bool {
	_, ok := map[string]struct{}{"if": {}, "then": {}, "else": {}, "fi": {}, "for": {}, "while": {}, "do": {}, "done": {}, "case": {}, "esac": {}, "function": {}, "time": {}, "command": {}, "builtin": {}, "exec": {}, "sudo": {}}[value]
	return ok
}

type riskAssessment struct {
	risk      Risk
	rationale MessageKey
}

func classify(words []string, containsSecret bool) Risk {
	return assessRisk(words, containsSecret).risk
}

func assessRisk(words []string, containsSecret bool) riskAssessment {
	if containsSecret || redact.ContainsSecret(words) {
		return riskAssessment{risk: RiskHigh, rationale: MessageRiskSecret}
	}
	if escalatesPrivileges(words) {
		return riskAssessment{risk: RiskHigh, rationale: MessageRiskPrivilegeEscalation}
	}
	if hasNetworkEffect(words) {
		return riskAssessment{risk: RiskHigh, rationale: MessageRiskNetworkEffect}
	}
	if mutatesFilesystem(words) {
		return riskAssessment{risk: RiskHigh, rationale: MessageRiskFilesystemMutation}
	}
	if knownSafeCommandLine(words) {
		return riskAssessment{risk: RiskSafe, rationale: MessageRiskRecognizedSafe}
	}
	return riskAssessment{risk: RiskUnknown, rationale: MessageRiskUnknown}
}

var privilegeEscalationCommands = map[string]struct{}{
	"doas": {}, "pkexec": {}, "runas": {}, "su": {}, "sudo": {}, "sudoedit": {},
}

func escalatesPrivileges(words []string) bool {
	for position, word := range words {
		if !commandStartAt(words, position) {
			continue
		}
		if _, ok := privilegeEscalationCommands[commandName(word)]; ok {
			return true
		}
	}
	return false
}

func commandStartAt(words []string, target int) bool {
	expectCommand := true
	for position, word := range words {
		if isCompoundOperator(word) {
			expectCommand = word != ")"
			continue
		}
		if !expectCommand {
			continue
		}
		if position == target {
			return true
		}
		if isShellKeyword(word) || assignmentWord(word) {
			continue
		}
		expectCommand = false
	}
	return false
}

var networkEffectCommands = map[string]struct{}{
	"curl": {}, "ftp": {}, "nc": {}, "ncat": {}, "netcat": {}, "scp": {}, "sftp": {}, "ssh": {}, "telnet": {}, "tftp": {}, "wget": {},
}

func hasNetworkEffect(words []string) bool {
	for position, word := range words {
		if !commandStartAt(words, position) {
			continue
		}
		command := commandName(word)
		if _, ok := networkEffectCommands[command]; ok {
			return true
		}
		if command == "git" && hasNetworkGitSubcommand(words[position+1:]) {
			return true
		}
	}
	return false
}

func hasNetworkGitSubcommand(words []string) bool {
	for _, word := range words {
		if isCompoundOperator(word) {
			return false
		}
		switch word {
		case "clone", "fetch", "ls-remote", "pull", "push":
			return true
		}
		if !strings.HasPrefix(word, "-") {
			return false
		}
	}
	return false
}

var safeCommands = map[string]struct{}{
	"basename": {}, "cat": {}, "dirname": {}, "echo": {}, "head": {}, "ls": {}, "printf": {}, "pwd": {}, "readlink": {}, "realpath": {}, "stat": {}, "true": {}, "uname": {}, "wc": {}, "which": {}, "whoami": {},
}

func knownSafeCommandLine(words []string) bool {
	if hasShellRedirection(words) {
		return false
	}
	positions := commandPositions(words)
	if len(positions) == 0 {
		return false
	}
	for _, position := range positions {
		command := commandName(words[position])
		if command == "git" {
			if !hasSafeGitSubcommand(words[position+1:]) {
				return false
			}
			continue
		}
		if _, ok := safeCommands[command]; !ok {
			return false
		}
	}
	return true
}

func hasSafeGitSubcommand(words []string) bool {
	for _, word := range words {
		if isCompoundOperator(word) {
			return false
		}
		if strings.HasPrefix(word, "-") {
			continue
		}
		switch word {
		case "diff", "log", "ls-files", "rev-parse", "show", "status":
			return true
		default:
			return false
		}
	}
	return true
}

func hasShellRedirection(words []string) bool {
	for _, word := range words {
		if strings.Contains(word, ">") {
			return true
		}
	}
	return false
}

var filesystemMutationCommands = map[string]struct{}{
	"chgrp": {}, "chmod": {}, "chown": {}, "cp": {}, "dd": {}, "install": {}, "ln": {}, "mkdir": {}, "mkfifo": {}, "mknod": {}, "mkfs": {}, "mv": {}, "patch": {}, "rm": {}, "rmdir": {}, "rsync": {}, "shred": {}, "tee": {}, "touch": {}, "truncate": {}, "unlink": {}, "wipefs": {},
}

func mutatesFilesystem(words []string) bool {
	for _, position := range commandPositions(words) {
		command := commandName(words[position])
		if _, ok := filesystemMutationCommands[command]; ok {
			return true
		}
		switch command {
		case "find":
			if hasArgument(words[position+1:], "-delete") {
				return true
			}
		case "sed", "perl":
			if hasArgument(words[position+1:], "-i") || hasArgument(words[position+1:], "--in-place") {
				return true
			}
		}
	}
	return false
}

func commandName(value string) string {
	if index := strings.LastIndexAny(value, "/\\"); index >= 0 {
		value = value[index+1:]
	}
	return strings.ToLower(value)
}

func hasArgument(words []string, value string) bool {
	for _, word := range words {
		if isCompoundOperator(word) {
			return false
		}
		if word == value {
			return true
		}
	}
	return false
}
