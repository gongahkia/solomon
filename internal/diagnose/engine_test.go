package diagnose

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/gongahkia/close-enough/internal/config"
)

func TestCommandTypoProducesHint(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	decision, err := New(Options{Config: config.Default(), Path: dir, CWD: dir}).Check("gti status", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Version != AdapterProtocolVersion || decision.Action != "hint" || decision.Suggestion != "git status" || decision.Risk != RiskSafe {
		t.Fatalf("unexpected decision: %#v", decision)
	}
}

func TestDiagnosticLimitsBoundInputOutputAndAnalysis(t *testing.T) {
	engine := New(Options{Config: config.Default()})
	if _, err := engine.Check(strings.Repeat("x", MaxInputBytes+1), "pre"); !errors.Is(err, ErrInputLimit) {
		t.Fatalf("input limit error = %v", err)
	}
	if _, err := New(Options{Config: config.Default(), Limits: Limits{OutputBytes: 1}}).Check("git sttaus", "pre"); !errors.Is(err, ErrOutputLimit) {
		t.Fatalf("output limit error = %v", err)
	}
	start := time.Unix(0, 0)
	clocks := []time.Time{start, start.Add(2 * time.Nanosecond)}
	index := 0
	clock := func() time.Time {
		value := clocks[index]
		index++
		return value
	}
	if _, err := New(Options{Config: config.Default(), Limits: Limits{AnalysisTime: time.Nanosecond}, Clock: clock}).Check("git sttaus", "pre"); !errors.Is(err, ErrAnalysisLimit) {
		t.Fatalf("analysis limit error = %v", err)
	}
}

func TestCheckContextPropagatesCancellationAndDeadline(t *testing.T) {
	engine := New(Options{Config: config.Default()})
	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	decision, err := engine.CheckContext(canceled, "git sttaus", "pre")
	if !errors.Is(err, context.Canceled) || decision.Action != "none" {
		t.Fatalf("canceled check = %#v, %v", decision, err)
	}
	deadline, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	if _, err := engine.CheckContext(deadline, "git sttaus", "pre"); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("deadline check error = %v", err)
	}
	active, cancel := context.WithCancel(context.Background())
	defer cancel()
	clock := func() time.Time {
		cancel()
		return time.Unix(0, 0)
	}
	if _, err := New(Options{Config: config.Default(), Clock: clock}).CheckContext(active, "git sttaus", "pre"); !errors.Is(err, context.Canceled) {
		t.Fatalf("in-flight cancellation error = %v", err)
	}
}

func TestProtocolEncodersLimitOutputSize(t *testing.T) {
	decision := Decision{Version: AdapterProtocolVersion, Action: "hint", Cause: strings.Repeat("x", MaxOutputBytes), Risk: RiskSafe}
	if _, err := decision.Record(); !errors.Is(err, ErrOutputLimit) {
		t.Fatalf("record output limit error = %v", err)
	}
	if _, err := decision.JSON("pre"); !errors.Is(err, ErrOutputLimit) {
		t.Fatalf("JSON output limit error = %v", err)
	}
}

func TestRecordCarriesAdapterProtocolVersion(t *testing.T) {
	decision := noDecision()
	record, err := decision.Record()
	if err != nil {
		t.Fatal(err)
	}
	fields := strings.Split(strings.TrimSuffix(record, "\n"), "\t")
	if len(fields) != 7 || fields[0] != "1" || fields[1] != "none" {
		t.Fatalf("unexpected record: %q", record)
	}
}

func TestRecordEncoderIsBinarySafeAndRejectsInvalidControlFields(t *testing.T) {
	decision := Decision{Version: AdapterProtocolVersion, Action: "hint", Risk: RiskSafe, Confidence: 0.5, Cause: "cause\t\x00", Consequence: "line\nnext", Suggestion: "\xff"}
	record, err := decision.Record()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(record, decision.Cause) || strings.Contains(record, decision.Consequence) || strings.Contains(record, decision.Suggestion) {
		t.Fatalf("record contains raw text: %q", record)
	}
	fields := strings.Split(strings.TrimSuffix(record, "\n"), "\t")
	for index, want := range []string{decision.Cause, decision.Consequence, decision.Suggestion} {
		got, err := base64.RawStdEncoding.DecodeString(fields[index+4])
		if err != nil || string(got) != want {
			t.Fatalf("record field %d = %q, %v", index+4, got, err)
		}
	}
	for _, decision := range []Decision{
		{Version: 2, Action: "hint", Risk: RiskSafe},
		{Version: AdapterProtocolVersion, Action: "invalid", Risk: RiskSafe},
		{Version: AdapterProtocolVersion, Action: "hint", Risk: Risk("invalid")},
		{Version: AdapterProtocolVersion, Action: "hint", Risk: RiskSafe, Confidence: math.NaN()},
	} {
		if _, err := decision.Record(); err == nil {
			t.Fatalf("accepted invalid record %#v", decision)
		}
	}
}

func TestJSONProtocolEncoderCompatibility(t *testing.T) {
	decision := Decision{Version: AdapterProtocolVersion, Action: "hint", Cause: "unknown command", Consequence: "shell rejects it", Suggestion: "git status", Class: RepairClassCommand, Evidence: []Evidence{{Kind: "resolver", Value: "path"}}, Confidence: 0.75, Risk: RiskSafe}
	data, err := decision.JSON("pre")
	if err != nil {
		t.Fatal(err)
	}
	var event Event
	if err := json.Unmarshal(data, &event); err != nil {
		t.Fatal(err)
	}
	if event.Version != AdapterProtocolVersion || event.Stage != "pre" || event.Action != "hint" || event.Risk != RiskSafe || event.Suggestion != "git status" || event.Class != RepairClassCommand || !slices.Equal(event.Evidence, decision.Evidence) {
		t.Fatalf("incompatible event: %#v", event)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		t.Fatal(err)
	}
	if _, ok := fields["command"]; ok {
		t.Fatalf("event exposes raw command: %s", data)
	}
	if _, err := decision.JSON("invalid"); err == nil {
		t.Fatal("accepted invalid JSON stage")
	}
	if _, err := (Decision{Version: AdapterProtocolVersion, Action: "invalid", Risk: RiskSafe}).JSON("pre"); err == nil {
		t.Fatal("accepted invalid JSON control fields")
	}
}

func TestGitSubcommandTypo(t *testing.T) {
	decision, err := New(Options{Config: config.Default()}).Check("git sttaus", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Suggestion != "git status" || decision.Cause != "unknown Git subcommand" {
		t.Fatalf("unexpected decision: %#v", decision)
	}
}

func TestConsequenceTemplatesCoverRepairClasses(t *testing.T) {
	for _, test := range []struct {
		class       RepairClass
		cause       string
		consequence string
	}{
		{RepairClassCommand, "command not found locally", "the shell would reject this command"},
		{RepairClassSemantic, "unknown Git subcommand", "Git will exit before performing work"},
		{RepairClassPath, "path does not exist", "the command may fail or target the wrong file"},
	} {
		template, ok := consequenceFor(test.class)
		if !ok || template.cause != test.cause || template.consequence != test.consequence {
			t.Fatalf("template(%s) = %#v, %t", test.class, template, ok)
		}
	}
	if _, ok := consequenceFor(RepairClass("unknown")); ok {
		t.Fatal("unknown repair class must not have a consequence template")
	}
}

func TestCommandDiffPreservesShellQuotingAndRedactsSecrets(t *testing.T) {
	line := `git "sttaus" --message 'keep quote'`
	decision, err := New(Options{Config: config.Default()}).Check(line, "pre")
	if err != nil {
		t.Fatal(err)
	}
	if got := decision.CommandDiff(line); got != "- git \"sttaus\" --message 'keep quote'\n+ git \"status\" --message 'keep quote'" {
		t.Fatalf("quoted diff = %q", got)
	}
	if got := decision.CommandDiffEmphasis(line); got != `git [-"sttaus"-]{+"status"+} --message 'keep quote'` {
		t.Fatalf("emphasized diff = %q", got)
	}
	repeated := Decision{original: "gti", replacement: "git", occurrence: 2}
	if got := repeated.CommandDiff("echo gti && gti status"); got != "- echo gti && gti status\n+ echo gti && git status" {
		t.Fatalf("repeated diff = %q", got)
	}
	secret := Decision{original: "gti", replacement: "git", occurrence: 1}
	if got := secret.CommandDiff("gti --token=top-secret"); got != "" {
		t.Fatalf("secret diff = %q", got)
	}
	if got := secret.CommandDiffEmphasis("gti --token=top-secret"); got != "" {
		t.Fatalf("secret emphasized diff = %q", got)
	}
}

func TestConfidenceThresholdsDifferByRepairClass(t *testing.T) {
	for _, test := range []struct {
		class     RepairClass
		threshold float64
	}{
		{RepairClassCommand, 0.60},
		{RepairClassSemantic, 0.75},
		{RepairClassPath, 0.90},
	} {
		if got := confidenceThreshold(test.class); got != test.threshold {
			t.Fatalf("%s threshold = %.2f, want %.2f", test.class, got, test.threshold)
		}
		if !meetsConfidenceThreshold(test.class, test.threshold) || meetsConfidenceThreshold(test.class, test.threshold-0.01) {
			t.Fatalf("%s threshold boundary was not enforced", test.class)
		}
	}
	if meetsConfidenceThreshold(RepairClass("unknown"), 1) {
		t.Fatal("unknown repair class must fail closed")
	}
}

func TestEvidenceCollectorUsesLocalDecisionFacts(t *testing.T) {
	evidence := collectEvidence(RepairClassCommand, "path", 1, 2.0/3.0)
	want := []Evidence{
		{Kind: "resolver", Value: "path"},
		{Kind: "edit_distance", Value: "1"},
		{Kind: "confidence_threshold", Value: "0.60"},
	}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	for _, test := range []struct {
		class    RepairClass
		resolver string
		distance int
		value    float64
	}{
		{RepairClass("unknown"), "path", 0, 1},
		{RepairClassCommand, "", 0, 1},
		{RepairClassCommand, "path", -1, 1},
		{RepairClassPath, "filesystem", 1, 0.89},
	} {
		if got := collectEvidence(test.class, test.resolver, test.distance, test.value); got != nil {
			t.Fatalf("invalid evidence = %#v", got)
		}
	}
}

func TestRepairClassesApplyTheirConfidenceThresholds(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	engine := New(Options{Config: config.Default(), Path: dir, CWD: dir})

	decision, err := engine.Check("gti status", "pre")
	if err != nil || decision.Class != RepairClassCommand || len(decision.Evidence) == 0 {
		t.Fatalf("command repair = %#v, %v", decision, err)
	}
	event := decision.Event("pre")
	if !slices.Equal(event.Evidence, decision.Evidence) {
		t.Fatalf("event evidence = %#v, want %#v", event.Evidence, decision.Evidence)
	}
	event.Evidence[0].Value = "mutated"
	if decision.Evidence[0].Value == "mutated" {
		t.Fatal("event evidence aliases decision evidence")
	}
	decision, err = engine.Check("git sttaus", "pre")
	if err != nil || decision.Class != RepairClassSemantic {
		t.Fatalf("semantic repair = %#v, %v", decision, err)
	}
	decision, err = engine.Check("git stzzus", "pre")
	if err != nil || decision.Action != "none" {
		t.Fatalf("low-confidence semantic repair = %#v, %v", decision, err)
	}

	if err := os.WriteFile(filepath.Join(dir, "report.txt"), []byte("report"), 0o600); err != nil {
		t.Fatal(err)
	}
	decision, err = engine.Check("cat ./reporx.txt", "pre")
	if err != nil || decision.Class != RepairClassPath {
		t.Fatalf("path repair = %#v, %v", decision, err)
	}
	decision, err = engine.Check("cat ./reporxx.txt", "pre")
	if err != nil || decision.Action != "none" {
		t.Fatalf("low-confidence path repair = %#v, %v", decision, err)
	}
}

func TestRewriteNeedsVeryHighConfidence(t *testing.T) {
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg}).Check("git statsu", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != "rewrite" {
		t.Fatalf("unexpected decision: %#v", decision)
	}
}

func TestSafeAutoApplyPolicy(t *testing.T) {
	base := Decision{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.90, Risk: RiskSafe}
	for _, test := range []struct {
		name     string
		mode     string
		enabled  bool
		decision Decision
		want     bool
	}{
		{"safe opted in", "rewrite", true, base, true},
		{"not opted in", "rewrite", false, base, false},
		{"wrong mode", "hint", true, base, false},
		{"high risk", "rewrite", true, Decision{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.90, Risk: RiskHigh}, false},
		{"unknown risk", "rewrite", true, Decision{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.90, Risk: RiskUnknown}, false},
		{"incomplete", "rewrite", true, Decision{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.90, Risk: RiskSafe, Incomplete: true}, false},
		{"below floor", "rewrite", true, Decision{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.79, Risk: RiskSafe}, false},
		{"unknown class", "rewrite", true, Decision{Suggestion: "git status", Class: RepairClass("unknown"), Confidence: 0.90, Risk: RiskSafe}, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			cfg := config.Default()
			cfg.Mode, cfg.AutoApplySafe = test.mode, test.enabled
			if got := New(Options{Config: cfg}).safeAutoApply(test.decision); got != test.want {
				t.Fatalf("safeAutoApply() = %t, want %t", got, test.want)
			}
		})
	}
}

func TestRewriteBufferPolicy(t *testing.T) {
	cfg := config.Default()
	cfg.Mode, cfg.AutoApplySafe = "rewrite", true
	engine := New(Options{Config: cfg})
	decision := Decision{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.90, Risk: RiskSafe}
	rewritten, ok := engine.evaluateRewriteBuffer(decision)
	if !ok || rewritten.Action != "rewrite" || decision.Action != "" {
		t.Fatalf("rewrite result = %#v, %t", rewritten, ok)
	}
	for _, blocked := range []Decision{
		{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.90, Risk: RiskHigh},
		{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.90, Risk: RiskUnknown},
		{Suggestion: "git status", Class: RepairClassSemantic, Confidence: 0.79, Risk: RiskSafe},
	} {
		unchanged, ok := engine.evaluateRewriteBuffer(blocked)
		if ok || unchanged.Action != blocked.Action || unchanged.Suggestion != blocked.Suggestion {
			t.Fatalf("blocked rewrite = %#v, %t", unchanged, ok)
		}
	}
}

func TestInterruptionPolicy(t *testing.T) {
	base := Decision{Suggestion: "diagnostic", Class: RepairClassCommand, Confidence: 0.90, Risk: RiskUnknown}
	for _, test := range []struct {
		name     string
		stage    string
		mode     string
		decision Decision
		want     bool
	}{
		{"unknown risk", "pre", "interrupt", base, true},
		{"high risk", "pre", "interrupt", Decision{Suggestion: "diagnostic", Class: RepairClassCommand, Confidence: 0.90, Risk: RiskHigh}, true},
		{"post stage", "post", "interrupt", base, false},
		{"wrong mode", "pre", "hint", base, false},
		{"incomplete", "pre", "interrupt", Decision{Suggestion: "diagnostic", Class: RepairClassCommand, Confidence: 0.90, Risk: RiskUnknown, Incomplete: true}, false},
		{"below threshold", "pre", "interrupt", Decision{Suggestion: "diagnostic", Class: RepairClassCommand, Confidence: 0.89, Risk: RiskUnknown}, false},
		{"unknown class", "pre", "interrupt", Decision{Suggestion: "diagnostic", Class: RepairClass("unknown"), Confidence: 1, Risk: RiskUnknown}, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			cfg := config.Default()
			cfg.Mode = test.mode
			if got := New(Options{Config: cfg}).shouldInterrupt(test.decision, test.stage); got != test.want {
				t.Fatalf("shouldInterrupt() = %t, want %t", got, test.want)
			}
		})
	}
}

func TestInterruptModeBlocksHighConfidenceRepair(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "diagnostic")
	cfg := config.Default()
	cfg.Mode = "interrupt"
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("diagnostci", "pre")
	if err != nil || decision.Action != "interrupt" || decision.Risk != RiskUnknown {
		t.Fatalf("interrupt decision: %#v, %v", decision, err)
	}
}

func TestPostCheckNeverInterrupts(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "diagnostic")
	cfg := config.Default()
	cfg.Mode = "interrupt"
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("diagnostci", "post")
	if err != nil || decision.Action == "interrupt" {
		t.Fatalf("post decision: %#v, %v", decision, err)
	}
}

func TestHighRiskNeverAutoApplied(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "rm")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("rmm -rf .", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action == "rewrite" || decision.Risk != RiskHigh {
		t.Fatalf("unsafe decision: %#v", decision)
	}
}

func TestFilesystemMutationClassifier(t *testing.T) {
	for _, line := range []string{
		"rm -rf target",
		`C:\\tools\\MV source target`,
		"echo ready && cp source target",
		"sed -i 's/a/b/' file",
		"find . -delete",
	} {
		words, err := tokenize(line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != RiskHigh {
			t.Fatalf("classify(%q) = %s, want high", line, got)
		}
	}
	for _, test := range []struct {
		line string
		risk Risk
	}{
		{"echo rm", RiskSafe},
		{"sed 's/a/b/' file", RiskUnknown},
		{"find . -name file", RiskUnknown},
	} {
		words, err := tokenize(test.line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != test.risk {
			t.Fatalf("classify(%q) = %s, want %s", test.line, got, test.risk)
		}
	}
}

func TestFilesystemMutationRepairNeverRewrites(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "mv")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("mvv source target", "pre")
	if err != nil || decision.Risk != RiskHigh || decision.Action == "rewrite" {
		t.Fatalf("unsafe filesystem decision: %#v, %v", decision, err)
	}
}

func TestPrivilegeEscalationClassifier(t *testing.T) {
	for _, line := range []string{
		"sudo -u root id",
		"doas id",
		"pkexec systemctl status service",
		"/usr/bin/SU -c id",
		"echo ready && runas /user:Administrator cmd",
	} {
		words, err := tokenize(line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != RiskHigh {
			t.Fatalf("classify(%q) = %s, want high", line, got)
		}
	}
	for _, test := range []struct {
		line string
		risk Risk
	}{
		{"echo sudo", RiskSafe},
		{"printf doas", RiskSafe},
		{"sudoku", RiskUnknown},
	} {
		words, err := tokenize(test.line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != test.risk {
			t.Fatalf("classify(%q) = %s, want %s", test.line, got, test.risk)
		}
	}
}

func TestPrivilegeEscalationRepairNeverRewrites(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "sudo")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("sudoo id", "pre")
	if err != nil || decision.Risk != RiskHigh || decision.Action == "rewrite" {
		t.Fatalf("unsafe privilege decision: %#v, %v", decision, err)
	}
}

func TestNetworkEffectClassifier(t *testing.T) {
	for _, line := range []string{
		"curl https://example.invalid",
		"wget https://example.invalid/file",
		"/usr/bin/SSH host",
		"echo ready && scp source host:target",
		"git push origin main",
	} {
		words, err := tokenize(line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != RiskHigh {
			t.Fatalf("classify(%q) = %s, want high", line, got)
		}
	}
	for _, test := range []struct {
		line string
		risk Risk
	}{
		{"echo curl", RiskSafe},
		{"git status", RiskSafe},
		{"curlish https://example.invalid", RiskUnknown},
	} {
		words, err := tokenize(test.line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != test.risk {
			t.Fatalf("classify(%q) = %s, want %s", test.line, got, test.risk)
		}
	}
}

func TestNetworkEffectRepairNeverRewrites(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "curl")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("crul https://example.invalid", "pre")
	if err != nil || decision.Risk != RiskHigh || decision.Action == "rewrite" {
		t.Fatalf("unsafe network decision: %#v, %v", decision, err)
	}
}

func TestSecretBearingArgumentsAreHighRisk(t *testing.T) {
	for _, line := range []string{
		"git --token top-secret",
		"git API_KEY=top-secret",
		"git --password top-secret",
		"git https://user:password@example.invalid/repo",
	} {
		words, err := tokenize(line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != RiskHigh {
			t.Fatalf("classify(%q) = %s, want high", line, got)
		}
	}
	for _, line := range []string{"git status", "git --format=json"} {
		words, err := tokenize(line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != RiskSafe {
			t.Fatalf("classify(%q) = %s, want safe", line, got)
		}
	}
}

func TestUnknownRiskFailsClosed(t *testing.T) {
	for _, line := range []string{"tool inspect", "git commit -m message", "cat source > target"} {
		words, err := tokenize(line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != RiskUnknown {
			t.Fatalf("classify(%q) = %s, want unknown", line, got)
		}
	}
	for _, line := range []string{"git status", "echo ready && git diff", "cat source"} {
		words, err := tokenize(line)
		if err != nil {
			t.Fatal(err)
		}
		if got := classify(words, false); got != RiskSafe {
			t.Fatalf("classify(%q) = %s, want safe", line, got)
		}
	}
}

func TestUnknownRiskRepairNeverRewrites(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "danger")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("denger target", "pre")
	if err != nil || decision.Risk != RiskUnknown || decision.Action == "rewrite" {
		t.Fatalf("unknown-risk decision: %#v, %v", decision, err)
	}
}

func TestIncompleteInputNeverEmitsRepair(t *testing.T) {
	decision, err := New(Options{Config: config.Default()}).Check("git 'status", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != "none" || !decision.Incomplete || decision.Suggestion != "" {
		t.Fatalf("unexpected incomplete decision: %#v", decision)
	}
}

func TestTokenizePlainQuotedAndEscapedWords(t *testing.T) {
	words, err := tokenize(`git commit -m "fix bug" path\ with\ spaces ''`)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"git", "commit", "-m", "fix bug", "path with spaces", ""}
	if !slices.Equal(words, want) {
		t.Fatalf("words = %#v, want %#v", words, want)
	}
}

func TestTokenizeRejectsIncompleteQuotedAndEscapedInput(t *testing.T) {
	for _, line := range []string{"git 'status", "git status\\"} {
		if _, err := tokenize(line); err == nil {
			t.Fatalf("expected tokenize failure for %q", line)
		}
	}
}

func TestTokenizeSeparatesUnquotedCompoundOperators(t *testing.T) {
	words, err := tokenize(`echo "a|b" && gti status; git sttaus | gti\|literal`)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"echo", "a|b", "&&", "gti", "status", ";", "git", "sttaus", "|", "gti|literal"}
	if !slices.Equal(words, want) {
		t.Fatalf("words = %#v, want %#v", words, want)
	}
}

func TestCommandPositionsResolveCompoundCommandStarts(t *testing.T) {
	words := []string{"MODE=1", "if", "gti", "&&", "echo", "ok", ";", "then", "git", "sttaus", ";", "fi"}
	if got := commandPositions(words); !slices.Equal(got, []int{2, 4, 8}) {
		t.Fatalf("positions = %#v", got)
	}
}

func TestCompoundCommandSuggestionsAndNonCommandArguments(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	engine := New(Options{Config: config.Default(), Path: dir, CWD: dir})
	decision, err := engine.Check("echo gti && gti status", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Suggestion != "echo gti && git status" {
		t.Fatalf("unexpected command suggestion: %#v", decision)
	}
	decision, err = engine.Check("echo ready; git sttaus", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Suggestion != "echo ready ; git status" {
		t.Fatalf("unexpected semantic suggestion: %#v", decision)
	}
	decision, err = engine.Check("echo gti", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != "none" {
		t.Fatalf("argument was treated as command: %#v", decision)
	}
}

func TestExecutableIndexCachesAndInvalidates(t *testing.T) {
	InvalidateExecutableIndex()
	directory := t.TempDir()
	writeExecutable(t, directory, "git")
	first := executableNames(directory)
	first[0] = "mutated"
	if got := executableNames(directory); !slices.Equal(got, []string{"git"}) {
		t.Fatalf("cached names mutated: %#v", got)
	}
	writeExecutable(t, directory, "go")
	if err := os.Chtimes(directory, time.Now(), time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	if got := executableNames(directory); !slices.Equal(got, []string{"git", "go"}) {
		t.Fatalf("directory change was not detected: %#v", got)
	}
	if err := os.Remove(filepath.Join(directory, "go")); err != nil {
		t.Fatal(err)
	}
	InvalidateExecutableIndex()
	if got := executableNames(directory); !slices.Equal(got, []string{"git"}) {
		t.Fatalf("explicit invalidation failed: %#v", got)
	}
}

func TestEngineCacheLifecycleAndIsolation(t *testing.T) {
	directory := t.TempDir()
	writeExecutable(t, directory, "git")
	defaults := Options{Config: config.Default(), Path: directory, CWD: directory}
	if first, second := New(defaults), New(defaults); first.cache == second.cache {
		t.Fatal("default engine caches are shared")
	}
	firstCache, secondCache := NewCache(), NewCache()
	first := New(Options{Config: config.Default(), Path: directory, CWD: directory, Cache: firstCache})
	second := New(Options{Config: config.Default(), Path: directory, CWD: directory, Cache: secondCache})
	for _, engine := range []Engine{first, second} {
		if _, err := engine.Check("gti status", "pre"); err != nil {
			t.Fatal(err)
		}
	}
	if cacheEntryCount(firstCache) == 0 || cacheEntryCount(secondCache) == 0 {
		t.Fatalf("unpopulated caches: %d, %d", cacheEntryCount(firstCache), cacheEntryCount(secondCache))
	}
	first.InvalidateCache()
	if cacheEntryCount(firstCache) != 0 || cacheEntryCount(secondCache) == 0 {
		t.Fatalf("cache invalidation leaked across engines: %d, %d", cacheEntryCount(firstCache), cacheEntryCount(secondCache))
	}
	if _, err := first.Check("gti status", "pre"); err != nil {
		t.Fatal(err)
	}
	first.Close()
	first.Close()
	if cacheEntryCount(firstCache) != 0 {
		t.Fatalf("cache retained entries after close: %d", cacheEntryCount(firstCache))
	}
}

func cacheEntryCount(cache *Cache) int {
	cache.RLock()
	defer cache.RUnlock()
	return len(cache.entries)
}

func TestExecutableCandidateNormalizationAcrossPlatforms(t *testing.T) {
	InvalidateExecutableIndex()
	directory := t.TempDir()
	if err := os.WriteFile(filepath.Join(directory, "Git.EXE"), []byte("binary"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "tool.cmd"), []byte("script"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "README.txt"), []byte("text"), 0o700); err != nil {
		t.Fatal(err)
	}
	if got := executableNamesFor(directory, "windows", ".EXE;.CMD"); !slices.Equal(got, []string{"git", "tool"}) {
		t.Fatalf("windows candidates = %#v", got)
	}
	if !commandExistsFor("GIT.EXE", directory, "windows", ".EXE;.CMD") || !commandExistsFor("git", directory, "windows", ".EXE;.CMD") || commandExistsFor("README.txt", directory, "windows", ".EXE;.CMD") {
		t.Fatal("unexpected Windows candidate matching")
	}
	if got := executableNamesFor(directory, "linux", ""); !slices.Equal(got, []string{"README.txt"}) {
		t.Fatalf("unix candidates = %#v", got)
	}
}

func TestDamerauLevenshteinScoresUnicodeAndTranspositions(t *testing.T) {
	for _, test := range []struct {
		a    string
		b    string
		want int
	}{
		{a: "gti", b: "git", want: 1},
		{a: "café", b: "cafe", want: 1},
		{a: "åb", b: "bå", want: 1},
		{a: "", b: "git", want: 3},
	} {
		if got := damerauLevenshtein(test.a, test.b); got != test.want {
			t.Fatalf("distance(%q, %q) = %d, want %d", test.a, test.b, got, test.want)
		}
	}
}

func TestNearestCandidateUsesDeterministicTieBreaker(t *testing.T) {
	if candidate, distance := nearest("c", []string{"x", "v"}); candidate != "v" || distance != 1 {
		t.Fatalf("nearest = %q, %d", candidate, distance)
	}
	if candidate, distance := nearest("c", nil); candidate != "" || distance != 0 {
		t.Fatalf("empty nearest = %q, %d", candidate, distance)
	}
}

func TestKeyboardAdjacencyBreaksEqualEditDistance(t *testing.T) {
	if adjacent, distant := keyboardAdjacencyDistance("gkt", "git"), keyboardAdjacencyDistance("gkt", "get"); adjacent >= distant {
		t.Fatalf("adjacent score = %d, distant score = %d", adjacent, distant)
	}
	if candidate, distance := nearest("gkt", []string{"get", "git"}); candidate != "git" || distance != 1 {
		t.Fatalf("nearest = %q, %d", candidate, distance)
	}
	if got := keyboardAdjacencyDistance("é", "e"); got != 2 {
		t.Fatalf("non-keyboard score = %d", got)
	}
}

func TestCandidateRankingUsesStableTieBreakers(t *testing.T) {
	ranked := rankCandidates("gkt", []string{"get", "git", "git", "go"})
	if got := []string{ranked[0].value, ranked[1].value, ranked[2].value}; !slices.Equal(got, []string{"git", "get", "go"}) {
		t.Fatalf("ranked candidates = %#v", got)
	}
	if len(rankCandidates("git", nil)) != 0 {
		t.Fatal("empty candidates must remain empty")
	}
}

func TestSecretBearingSuggestionIsRedactedAndNeverRewritten(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("gti --token=super-secret", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action == "rewrite" || decision.Risk != RiskHigh || decision.Suggestion != "git --token=[REDACTED]" {
		t.Fatalf("unsafe decision: %#v", decision)
	}
	data, err := decision.JSON("pre")
	if err != nil {
		t.Fatal(err)
	}
	record, err := decision.Record()
	if err != nil {
		t.Fatal(err)
	}
	if string(data) == "" || contains(string(data), "super-secret") || contains(string(data), `"command":`) || contains(record, "super-secret") {
		t.Fatalf("secret leaked in diagnostic: %s", data)
	}
}

func TestEventContainsOnlyDiagnosticMetadata(t *testing.T) {
	event := Decision{Version: AdapterProtocolVersion, Action: "hint", Suggestion: "git status", Risk: RiskSafe}.Event("post")
	if event.Stage != "post" || event.Suggestion != "git status" || event.Version != AdapterProtocolVersion {
		t.Fatalf("unexpected event: %#v", event)
	}
	data, err := Decision{Version: AdapterProtocolVersion, Action: "hint", Suggestion: "git status", Risk: RiskSafe}.JSON("post")
	if err != nil {
		t.Fatal(err)
	}
	if contains(string(data), `"command":`) {
		t.Fatalf("event exposes raw command field: %s", data)
	}
}

func contains(value, substring string) bool {
	for index := 0; index+len(substring) <= len(value); index++ {
		if value[index:index+len(substring)] == substring {
			return true
		}
	}
	return false
}

func writeExecutable(t *testing.T, dir, name string) {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"), 0o700); err != nil {
		t.Fatal(err)
	}
}
