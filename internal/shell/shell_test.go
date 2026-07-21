package shell

import (
	"encoding/base64"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

type compatibilityFixture struct {
	Name          string          `json:"name"`
	Shell         string          `json:"shell"`
	Tier          string          `json:"tier"`
	Capabilities  []Capability    `json:"capabilities"`
	Configuration []Configuration `json:"configuration"`
	Limitations   []string        `json:"limitations"`
	Markers       []string        `json:"markers"`
}

type commandInjectionFixture struct {
	Name    string `json:"name"`
	Payload string `json:"payload"`
}

type adapterProtocolFixture struct {
	Name    string `json:"name"`
	Version int    `json:"version"`
	Record  bool   `json:"record"`
}

func TestResolveAction(t *testing.T) {
	tests := []struct {
		name, action, risk, suggestion string
		want                           ActionResult
	}{
		{"none", "none", "safe", "", ActionResult{Submit: true}},
		{"run unchanged", "run-unchanged", "high", "rm", ActionResult{Submit: true}},
		{"skip once", "skip-once", "high", "rm", ActionResult{Submit: true}},
		{"hint", "hint", "safe", "git status", ActionResult{Render: true, Submit: true}},
		{"interrupt", "interrupt", "high", "rm", ActionResult{Render: true}},
		{"rewrite", "rewrite", "safe", "git status", ActionResult{Rewrite: true}},
		{"edit buffer", "edit-in-buffer", "safe", "git status", ActionResult{Rewrite: true}},
		{"unsafe rewrite", "rewrite", "high", "rm", ActionResult{Render: true, Refused: true}},
		{"empty rewrite", "rewrite", "safe", "", ActionResult{Render: true, Refused: true}},
		{"unknown", "invalid", "safe", "", ActionResult{Submit: true}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := ResolveAction(test.action, test.risk, test.suggestion); got != test.want {
				t.Fatalf("ResolveAction() = %#v, want %#v", got, test.want)
			}
		})
	}
}

func TestInlineDiagnostic(t *testing.T) {
	if got := InlineDiagnostic("safe", "0.91", "git status"); got != "close-enough [safe/0.91]: git status" {
		t.Fatalf("InlineDiagnostic() = %q", got)
	}
}

func TestRiskConfirmation(t *testing.T) {
	if got := RiskConfirmation("safe", "git status"); got.Required || got.Message != "" {
		t.Fatalf("safe confirmation = %#v", got)
	}
	if got := RiskConfirmation("high", "rm -rf target"); !got.Required || got.Message != "confirm high-risk repair: rm -rf target" {
		t.Fatalf("risky confirmation = %#v", got)
	}
}

func TestLowConfidenceHintIsNonBlocking(t *testing.T) {
	if got := LowConfidenceHint(0.79); !got.Render || !got.Submit {
		t.Fatalf("low confidence action = %#v", got)
	}
	if got := LowConfidenceHint(0.80); got != (ActionResult{}) {
		t.Fatalf("threshold action = %#v", got)
	}
}

func TestLowConfidenceInterruptRequiresOptIn(t *testing.T) {
	if got := LowConfidenceInterrupt(0.5, false); got != (ActionResult{}) {
		t.Fatalf("unopted action = %#v", got)
	}
	if got := LowConfidenceInterrupt(0.5, true); !got.Render || got.Submit {
		t.Fatalf("opted action = %#v", got)
	}
}

func TestLowConfidenceKeybindingInterruptRequiresInvocation(t *testing.T) {
	if got := LowConfidenceKeybindingInterrupt(0.5, false); got != (ActionResult{}) {
		t.Fatalf("uninvoked action = %#v", got)
	}
	if got := LowConfidenceKeybindingInterrupt(0.5, true); !got.Render || got.Submit {
		t.Fatalf("invoked action = %#v", got)
	}
}

func TestRenderCandidateSelector(t *testing.T) {
	candidates := []string{"git status", "git add", "git status", "", "git commit", "git diff", "git log", "git show"}
	if got := RenderCandidateSelector(candidates); got != "1. git add\n2. git commit\n3. git diff\n4. git log\n5. git show" {
		t.Fatalf("selector = %q", got)
	}
}

func TestTruncateForWidth(t *testing.T) {
	tests := []struct {
		value string
		width int
		want  string
	}{
		{"git status", 20, "git status"},
		{"git status", 6, "git s…"},
		{"世界", 1, "…"},
		{"git", 0, ""},
	}
	for _, test := range tests {
		if got := TruncateForWidth(test.value, test.width); got != test.want {
			t.Fatalf("TruncateForWidth(%q, %d) = %q, want %q", test.value, test.width, got, test.want)
		}
	}
}

func TestAdaptersRateLimitDiagnosticsPerSession(t *testing.T) {
	for _, test := range []struct {
		shell        string
		count        string
		allow        string
		hintAllow    string
		hint         string
		interrupt    string
		interruptEnd string
		post         string
	}{
		{"zsh", "_CLOSE_ENOUGH_DIAGNOSTIC_COUNT=0", "_close_enough_allow_diagnostic", "_close_enough_allow_suggestion", `if [[ "$action" == hint ]]; then`, `if [[ "$action" == interrupt ]]; then`, "  return 1\n  fi", "daemon request --operation post-failure --shell zsh"},
		{"bash", "_close_enough_diagnostic_count=0", "_close_enough_allow_diagnostic", "_close_enough_allow_suggestion", `if [ "$action" = hint ]; then`, `if [ "$action" = interrupt ]; then`, "  return 1\n  fi", "daemon request --operation post-failure --shell bash"},
		{"fish", "_CLOSE_ENOUGH_DIAGNOSTIC_COUNT 0", "_close_enough_allow_diagnostic", "_close_enough_allow_suggestion", `if test "$fields[2]" = hint`, `if test "$fields[2]" = interrupt`, "    return\n  end", "daemon request --operation post-failure --shell fish"},
		{"pwsh", "CloseEnoughDiagnosticCount = 0", "Allow-CloseEnoughDiagnostic", "Allow-CloseEnoughSuggestion", "if ($decision.action -eq 'hint')", "if ($decision.action -eq 'interrupt')", "    return\n  }", "$output = (& close-enough check --stage post"},
	} {
		t.Run(test.shell, func(t *testing.T) {
			script, err := Script(test.shell)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(script, test.count) || !strings.Contains(script, test.allow) || !strings.Contains(script, test.post) {
				t.Fatalf("%s adapter lacks session rate limiting: %q", test.shell, script)
			}
			hintStart, interruptStart := strings.Index(script, test.hint), strings.Index(script, test.interrupt)
			if hintStart < 0 || interruptStart < hintStart || !strings.Contains(script[hintStart:interruptStart], test.hintAllow) {
				t.Fatalf("%s hint is not rate limited: %q", test.shell, script)
			}
			interrupt := script[interruptStart:]
			if end := strings.Index(interrupt, test.interruptEnd); end < 0 {
				t.Fatalf("%s interrupt does not return before execution: %q", test.shell, interrupt)
			} else {
				interrupt = interrupt[:end]
			}
			if strings.Contains(interrupt, test.allow) {
				t.Fatalf("%s interrupt is rate limited: %q", test.shell, interrupt)
			}
		})
	}
}

func TestAdaptersSuppressRepeatedSuggestions(t *testing.T) {
	for _, test := range []struct {
		shell string
		cache string
		allow string
	}{
		{"zsh", "typeset -gA _CLOSE_ENOUGH_SEEN_SUGGESTIONS", "_close_enough_allow_suggestion"},
		{"bash", "_close_enough_seen_suggestions=$'\\n'", "_close_enough_allow_suggestion"},
		{"fish", "set -g _CLOSE_ENOUGH_SEEN_SUGGESTIONS", "_close_enough_allow_suggestion"},
		{"pwsh", "CloseEnoughSeenSuggestions = [System.Collections.Generic.HashSet[string]]::new()", "Allow-CloseEnoughSuggestion"},
	} {
		t.Run(test.shell, func(t *testing.T) {
			script, err := Script(test.shell)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(script, test.cache) || !strings.Contains(script, test.allow) {
				t.Fatalf("%s adapter lacks repeated-suggestion cache: %q", test.shell, script)
			}
		})
	}
}

func TestZshSuppressesRepeatedSuggestions(t *testing.T) {
	zsh, err := exec.LookPath("zsh")
	if err != nil {
		t.Skip("zsh unavailable")
	}
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	scriptPath := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(scriptPath, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$RECORD\"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	record := "1\thint\tsafe\t0.90\t\t\t" + base64.StdEncoding.EncodeToString([]byte("git status"))
	harness := `zle() { [[ "$1" == -M ]] && print -r -- "$2"; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; repeat 6 { BUFFER=gti; _close_enough_check; }`
	command := exec.Command(zsh, "-fc", harness, "zsh", scriptPath)
	command.Env = append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "RECORD="+record)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("zsh rate-limit harness: %v: %s", err, output)
	}
	if got := strings.Count(string(output), "close-enough [safe/0.90]: git status"); got != 1 {
		t.Fatalf("rendered hints = %d, want 1: %s", got, output)
	}
}

func TestOneTimeAccept(t *testing.T) {
	var accept OneTimeAccept
	if !accept.Accept("rewrite:git-status") || accept.Accept("rewrite:git-status") || accept.Accept("") || !accept.Accept("rewrite:git-log") {
		t.Fatal("one-time acceptance state is incorrect")
	}
}

func TestSkipOnce(t *testing.T) {
	var skip SkipOnce
	if !skip.Skip("gti") || skip.Skip("gti") || skip.Skip("") || !skip.Skip("git sttaus") {
		t.Fatal("skip-once state is incorrect")
	}
}

func TestRuleSuppressions(t *testing.T) {
	var suppressions RuleSuppressions
	if !suppressions.Suppress(" core-git ") || suppressions.Suppress("core-git") || suppressions.Suppress("") || !suppressions.Suppressed("core-git") || suppressions.Suppressed("resolver:path") {
		t.Fatal("rule suppression state is incorrect")
	}
}

func TestSafeRuleAcceptances(t *testing.T) {
	var acceptances SafeRuleAcceptances
	if acceptances.Accept("core-git", "high") || acceptances.Accept("", "safe") || !acceptances.Accept("core-git", "safe") || acceptances.Accept("core-git", "safe") || !acceptances.Accepted("core-git") {
		t.Fatal("safe rule acceptance state is incorrect")
	}
}

func TestAdaptersUseCompactInlineDiagnosticLayout(t *testing.T) {
	markers := map[string]string{
		"zsh":        `close-enough [$risk/$confidence]: $suggestion`,
		"bash":       `close-enough [%s/%s]: %s`,
		"fish":       `close-enough [$fields[3]/$fields[4]]: $suggestion`,
		"powershell": `close-enough [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion)`,
	}
	for name, marker := range markers {
		script, err := Script(name)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(script, marker) {
			t.Fatalf("%s adapter lacks compact inline layout %q", name, marker)
		}
	}
}

func TestAdapterCompatibilityFixtures(t *testing.T) {
	data, err := os.ReadFile("testdata/adapter_contracts.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []compatibilityFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	for _, fixture := range fixtures {
		t.Run(fixture.Name, func(t *testing.T) {
			contract, err := ContractFor(fixture.Name)
			if err != nil {
				t.Fatal(err)
			}
			if contract.Shell != fixture.Shell || contract.Tier != fixture.Tier || !slices.Equal(contract.Capabilities, fixture.Capabilities) || !slices.Equal(contract.Configuration, fixture.Configuration) || !slices.Equal(contract.Limitations, fixture.Limitations) {
				t.Fatalf("contract = %#v, fixture = %#v", contract, fixture)
			}
			script, err := Script(fixture.Name)
			if err != nil {
				t.Fatal(err)
			}
			for _, marker := range fixture.Markers {
				if !strings.Contains(script, marker) {
					t.Fatalf("script lacks compatibility marker %q", marker)
				}
			}
			doctor := Doctor("/bin/"+fixture.Name, "test")
			if !doctor.Supported || doctor.Tier != fixture.Tier || !slices.Equal(doctor.Features, capabilityStrings(fixture.Capabilities)) || !slices.Equal(doctor.Configuration, configurationStrings(fixture.Configuration)) || !slices.Equal(doctor.Limitations, fixture.Limitations) {
				t.Fatalf("doctor = %#v, fixture = %#v", doctor, fixture)
			}
		})
	}
}

func TestCommandInjectionRegressionCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/command_injection.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []commandInjectionFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("command injection corpus is empty")
	}
	for _, shellName := range []string{"zsh", "bash", "fish"} {
		shellPath, err := exec.LookPath(shellName)
		if err != nil {
			t.Run(shellName, func(t *testing.T) { t.Skip(shellName + " unavailable") })
			continue
		}
		for _, fixture := range fixtures {
			t.Run(shellName+"/"+fixture.Name, func(t *testing.T) {
				if fixture.Name == "" || fixture.Payload == "" {
					t.Fatalf("invalid command injection fixture: %#v", fixture)
				}
				runCommandInjectionFixture(t, shellName, shellPath, fixture)
			})
		}
	}
}

func TestAdapterProtocolCrossVersionContracts(t *testing.T) {
	data, err := os.ReadFile("testdata/adapter_protocol_versions.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []adapterProtocolFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("adapter protocol version corpus is empty")
	}
	version := strconv.Itoa(diagnose.AdapterProtocolVersion)
	guards := map[string]string{
		"zsh":        `[[ "$version" == "` + version + `" ]] || return 0`,
		"bash":       `[ "$version" = ` + version + ` ] || return`,
		"fish":       `if test "$fields[1]" != ` + version,
		"powershell": `$decision.version -ne ` + version,
	}
	for _, fixture := range fixtures {
		t.Run(fixture.Name, func(t *testing.T) {
			if fixture.Name == "" || fixture.Version < 0 {
				t.Fatalf("invalid adapter protocol fixture: %#v", fixture)
			}
			decision := diagnose.Decision{Version: fixture.Version, Action: "hint", Suggestion: "git status", Confidence: 0.90, Risk: diagnose.RiskSafe}
			record, err := decision.Record()
			if (err == nil) != fixture.Record {
				t.Fatalf("Record(version=%d) error = %v, want record=%t", fixture.Version, err, fixture.Record)
			}
			if fixture.Record && !strings.HasPrefix(record, version+"\t") {
				t.Fatalf("record = %q, want protocol version %q", record, version)
			}
			data, err := decision.JSON("pre")
			if (err == nil) != fixture.Record {
				t.Fatalf("JSON(version=%d) error = %v, want record=%t", fixture.Version, err, fixture.Record)
			}
			if fixture.Record && !strings.Contains(string(data), `"version":`+version) {
				t.Fatalf("JSON = %q, want protocol version %q", data, version)
			}
			for shellName, guard := range guards {
				script, err := Script(shellName)
				if err != nil {
					t.Fatal(err)
				}
				if !strings.Contains(script, guard) {
					t.Fatalf("%s adapter lacks protocol guard %q", shellName, guard)
				}
			}
		})
	}
}

func runCommandInjectionFixture(t *testing.T, shellName, shellPath string, fixture commandInjectionFixture) {
	t.Helper()
	script, err := Script(shellName)
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	adapter := filepath.Join(directory, "adapter."+shellName)
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	checkerScript := "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$CAPTURE\"\nif [ \"$7\" = \"$COMMAND_INPUT\" ]; then\n  printf '%s\\n' \"$COMMAND_RECORD\"\nelif [ \"$7\" = \"$SAFE_INPUT\" ]; then\n  printf '%s\\n' \"$SAFE_RECORD\"\nelse\n  printf '%s\\n' \"$HIGH_RECORD\"\nfi\n"
	if err := os.WriteFile(checker, []byte(checkerScript), 0o700); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "arguments")
	commandResult := filepath.Join(directory, "command-buffer")
	rewriteResult := filepath.Join(directory, "rewrite-buffer")
	highRiskResult := filepath.Join(directory, "high-risk-buffer")
	marker := filepath.Join(directory, "marker")
	safeInput, highInput := "close-enough-safe-rewrite", "close-enough-high-rewrite"
	env := append(os.Environ(),
		"PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"),
		"CAPTURE="+capture,
		"COMMAND_INPUT="+fixture.Payload,
		"COMMAND_RECORD="+commandInjectionRecord("hint", "safe", fixture.Payload),
		"SAFE_INPUT="+safeInput,
		"SAFE_RECORD="+commandInjectionRecord("rewrite", "safe", fixture.Payload),
		"HIGH_INPUT="+highInput,
		"HIGH_RECORD="+commandInjectionRecord("rewrite", "high", fixture.Payload),
		"COMMAND_RESULT="+commandResult,
		"REWRITE_RESULT="+rewriteResult,
		"HIGH_RISK_RESULT="+highRiskResult,
		"MARKER="+marker,
	)
	var command *exec.Cmd
	switch shellName {
	case "zsh":
		harness := `zle() { :; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; BUFFER="$2"; _close_enough_check; print -rn -- "$BUFFER" > "$COMMAND_RESULT"; BUFFER="$SAFE_INPUT"; _close_enough_check; print -rn -- "$BUFFER" > "$REWRITE_RESULT"; BUFFER="$HIGH_INPUT"; _close_enough_check; print -rn -- "$BUFFER" > "$HIGH_RISK_RESULT"`
		command = exec.Command(shellPath, "-fc", harness, "zsh", adapter, fixture.Payload)
	case "bash":
		harness := `source "$1"; READLINE_LINE="$2"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$COMMAND_RESULT"; READLINE_LINE="$SAFE_INPUT"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$REWRITE_RESULT"; READLINE_LINE="$HIGH_INPUT"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$HIGH_RISK_RESULT"`
		command = exec.Command(shellPath, "--noprofile", "--norc", "-c", harness, "bash", adapter, fixture.Payload)
	case "fish":
		harness := `function bind; if test (count $argv) -eq 1; echo "bind --preset enter execute"; end; end; function commandline; if test "$argv[1]" = -b; printf '%s' "$BUFFER"; else if test "$argv[1]" = -r; set -g BUFFER "$argv[2]"; end; end; source "$argv[1]"; set -g BUFFER "$argv[2]"; _close_enough_accept_line; printf '%s' "$BUFFER" > "$COMMAND_RESULT"; set -g BUFFER "$SAFE_INPUT"; _close_enough_accept_line; printf '%s' "$BUFFER" > "$REWRITE_RESULT"; set -g BUFFER "$HIGH_INPUT"; _close_enough_accept_line; printf '%s' "$BUFFER" > "$HIGH_RISK_RESULT"`
		command = exec.Command(shellPath, "-c", harness, adapter, fixture.Payload)
	default:
		t.Fatalf("unsupported shell %q", shellName)
	}
	command.Env = env
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("%s harness: %v\n%s", shellName, err, output)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("%s adapter evaluated payload: %v", shellName, err)
	}
	for _, result := range []string{commandResult, rewriteResult} {
		buffer, err := os.ReadFile(result)
		if err != nil || string(buffer) != fixture.Payload {
			t.Fatalf("buffer = %q, %v; want %q", buffer, err, fixture.Payload)
		}
	}
	highRiskBuffer, err := os.ReadFile(highRiskResult)
	if err != nil {
		t.Fatal(err)
	}
	if string(highRiskBuffer) == fixture.Payload {
		t.Fatalf("%s applied high-risk rewrite %q", shellName, fixture.Payload)
	}
	arguments, err := os.ReadFile(capture)
	if err != nil || !strings.Contains(string(arguments), fixture.Payload) {
		t.Fatalf("checker arguments = %q, %v", arguments, err)
	}
}

func commandInjectionRecord(action, risk, payload string) string {
	return "1\t" + action + "\t" + risk + "\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte(payload))
}

func TestFishInterruptPreventsExecution(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	interrupt := strings.Index(script, `if test "$fields[2]" = interrupt`)
	if interrupt < 0 {
		t.Fatalf("fish interrupt branch is missing: %q", script)
	}
	branch := script[interrupt:]
	execute := strings.Index(branch, "commandline -f execute")
	if execute < 0 || !strings.Contains(branch[:execute], "commandline -f repaint") || !strings.Contains(branch[:execute], "return") {
		t.Fatalf("fish interrupt does not precede execution: %q", script)
	}
}

func TestZshInitializationIsGuardedAndRetainsInterrupt(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	guard := "if (( ! ${+_CLOSE_ENOUGH_ZSH_LOADED} )); then"
	marker := "typeset -g _CLOSE_ENOUGH_ZSH_LOADED=1"
	interrupt := `if [[ "$action" == interrupt ]]; then`
	accept := `zle "$_CLOSE_ENOUGH_ENTER_WIDGET"`
	if !strings.HasPrefix(script, "# close-enough zsh integration\n"+guard+"\n"+marker) || !strings.HasSuffix(strings.TrimSpace(script), "fi") {
		t.Fatalf("zsh script lacks an enclosing idempotence guard: %q", script)
	}
	interruptStart := strings.Index(script, interrupt)
	if strings.Count(script, marker) != 1 || interruptStart < 0 || interruptStart > strings.Index(script, accept) || !strings.Contains(script[interruptStart:], "return 1") {
		t.Fatalf("zsh script does not preserve one guarded interrupt path: %q", script)
	}
}

func TestZshPreExecutionUsesCapturedBuffer(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	capture := `command="$BUFFER"`
	check := `--stage pre --format record --command "$command"`
	if strings.Index(script, capture) < 0 || strings.Index(script, check) < strings.Index(script, capture) || strings.Contains(script, `--command "$BUFFER"`) {
		t.Fatalf("zsh pre-execution check does not use a captured buffer: %q", script)
	}
	if !strings.Contains(script, `2>/dev/null)" || return 0`) {
		t.Fatalf("zsh check failure does not preserve normal submission: %q", script)
	}
}

func TestZshHintRenderingDoesNotSuppressSubmission(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	hint := `if [[ "$action" == hint ]]; then`
	interrupt := `if [[ "$action" == interrupt ]]; then`
	start, end := strings.Index(script, hint), strings.Index(script, interrupt)
	if start < 0 || end < start || !strings.Contains(script[start:end], "zle -M") || !strings.Contains(script[start:end], "return 0") {
		t.Fatalf("zsh hint path is not non-blocking: %q", script)
	}
	if strings.Index(script, `zle "$_CLOSE_ENOUGH_ENTER_WIDGET"`) < end || !strings.Contains(script[end:], "return 1") {
		t.Fatalf("zsh interrupt path does not retain the confirmation boundary: %q", script)
	}
}

func TestZshInterruptReturnsBeforeCommandExecution(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	interrupt := `if [[ "$action" == interrupt ]]; then`
	widget := "function _close_enough_accept_line {"
	interruptStart, widgetStart := strings.Index(script, interrupt), strings.Index(script, widget)
	if interruptStart < 0 || widgetStart < interruptStart || !strings.Contains(script[interruptStart:widgetStart], "return 1") {
		t.Fatalf("zsh interrupt does not suppress command submission: %q", script)
	}
	widgetEnd := strings.Index(script[widgetStart:], "zle -N _close_enough_accept_line")
	if widgetEnd < 0 || !strings.Contains(script[widgetStart:widgetStart+widgetEnd], "if ! _close_enough_check; then\n    return 0\n  fi\n  zle \"$_CLOSE_ENOUGH_ENTER_WIDGET\"") {
		t.Fatalf("zsh enter widget executes without an explicit suppression gate: %q", script)
	}
}

func TestZshEnterBindingIsCollisionSafeAndRestorable(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	bind := `binding="$(bindkey -M main '^M')" || return 0`
	widget := `widget="${binding##* }"`
	install := `bindkey -M main '^M' _close_enough_accept_line`
	restore := `bindkey -M main '^M' "$_CLOSE_ENOUGH_ENTER_WIDGET"`
	if !strings.Contains(script, bind) || !strings.Contains(script, widget) || !strings.Contains(script, install) || !strings.Contains(script, `[[ "$binding" == *" _close_enough_accept_line" ]] || return 0`) || !strings.Contains(script, restore) || strings.Contains(script, "bindkey '^M' _close_enough_accept_line") {
		t.Fatalf("zsh Enter binding is not collision-safe and restorable: %q", script)
	}
}

func TestZshRestoresPreexistingEnterBinding(t *testing.T) {
	zsh, err := exec.LookPath("zsh")
	if err != nil {
		t.Skip("zsh unavailable")
	}
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	scriptPath := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(scriptPath, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "bindings")
	harness := `current=existing-widget; zle() { :; }; bindkey() { if [[ "$#" == 3 ]]; then print '"^M" '$current; else current="$4"; print -r -- "$current" >> "$CAPTURE"; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; _close_enough_restore_enter; print -r -- "$current"`
	command := exec.Command(zsh, "-fc", harness, "zsh", scriptPath)
	command.Env = append(os.Environ(), "CAPTURE="+capture)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("zsh harness: %v\n%s", err, output)
	}
	if got := string(output); got != "existing-widget\n" {
		t.Fatalf("restored binding = %q", got)
	}
	bindings, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(bindings); got != "_close_enough_accept_line\nexisting-widget\n" {
		t.Fatalf("binding changes = %q", got)
	}
}

func TestZshAdapterDoesNotEvaluateCommandOrRewritePayloads(t *testing.T) {
	zsh, err := exec.LookPath("zsh")
	if err != nil {
		t.Skip("zsh unavailable")
	}
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	scriptPath := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(scriptPath, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '%s\\n' \"$RECORD\" ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct {
		name   string
		input  string
		action string
		want   string
	}{
		{name: "command", input: `$(touch "$MARKER") ; echo injected`, action: "hint", want: `$(touch "$MARKER") ; echo injected`},
		{name: "rewrite", input: "gti", action: "rewrite", want: `$(touch "$MARKER")`},
	} {
		t.Run(test.name, func(t *testing.T) {
			capture := filepath.Join(directory, test.name+"-arguments")
			result := filepath.Join(directory, test.name+"-buffer")
			marker := filepath.Join(directory, test.name+"-marker")
			payload := test.input
			if test.name == "rewrite" {
				payload = test.want
			}
			record := "1\t" + test.action + "\tsafe\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte(payload))
			harness := `zle() { :; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; BUFFER="$2"; _close_enough_check; print -rn -- "$BUFFER" > "$RESULT"`
			command := exec.Command(zsh, "-fc", harness, "zsh", scriptPath, test.input)
			command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "RESULT="+result, "RECORD="+record, "MARKER="+marker)
			if output, err := command.CombinedOutput(); err != nil {
				t.Fatalf("zsh harness: %v\n%s", err, output)
			}
			if _, err := os.Stat(marker); !os.IsNotExist(err) {
				t.Fatalf("adapter evaluated payload: %v", err)
			}
			buffer, err := os.ReadFile(result)
			if err != nil || string(buffer) != test.want {
				t.Fatalf("buffer = %q, %v; want %q", buffer, err, test.want)
			}
			if test.name == "command" {
				arguments, err := os.ReadFile(capture)
				if err != nil || !strings.Contains(string(arguments), test.input) {
					t.Fatalf("checker arguments = %q, %v", arguments, err)
				}
			}
		})
	}
}

func TestZshSafeRewriteSubmitsOnSecondEnter(t *testing.T) {
	zsh, err := exec.LookPath("zsh")
	if err != nil {
		t.Skip("zsh unavailable")
	}
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	scriptPath := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(scriptPath, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '%s\\n' \"$RECORD\" ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "calls")
	record := "1\trewrite\tsafe\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte("git status"))
	harness := `zle() { :; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; BUFFER=gti; _close_enough_check; first=$?; first_buffer="$BUFFER"; _close_enough_check; second=$?; print -r -- "$first|$first_buffer|$second|$BUFFER"`
	command := exec.Command(zsh, "-fc", harness, "zsh", scriptPath)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "RECORD="+record)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("zsh harness: %v\n%s", err, output)
	}
	if got := string(output); got != "1|git status|0|git status\n" {
		t.Fatalf("rewrite flow = %q", got)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "daemon request"); got != 2 {
		t.Fatalf("daemon requests = %d, want 2: %q", got, calls)
	}
}

func TestZshHighRiskConfirmationSubmitsOnSecondEnter(t *testing.T) {
	zsh, err := exec.LookPath("zsh")
	if err != nil {
		t.Skip("zsh unavailable")
	}
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	scriptPath := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(scriptPath, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *\"--operation pre-send\"*) count=0; test -f \"$STATE\" && count=$(cat \"$STATE\"); if test \"$count\" = 0; then printf '1\\tinterrupt\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; printf 1 > \"$STATE\"; else printf '1\\tsubmit\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; fi ;; *) exit 1 ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "calls")
	state := filepath.Join(directory, "state")
	suggestion := base64.StdEncoding.EncodeToString([]byte("git push --force"))
	harness := `zle() { :; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; BUFFER='git push --force'; _close_enough_check; first=$?; _close_enough_check; second=$?; print -r -- "$first|$second|$BUFFER"`
	command := exec.Command(zsh, "-fc", harness, "zsh", scriptPath)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "STATE="+state, "SUGGESTION="+suggestion)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("zsh harness: %v\n%s", err, output)
	}
	if got := string(output); got != "1|0|git push --force\n" {
		t.Fatalf("confirmation flow = %q", got)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "daemon request"); got != 3 {
		t.Fatalf("daemon requests = %d, want 3: %q", got, calls)
	}
}

func TestZshInteractivePTYInterruptPreventsExecution(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '1\\tinterrupt\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
spawn -noecho zsh -f
expect -re {[%#] $}
send -- "PROMPT='CE> '\r"
expect "CE> "
send -- "source \$ADAPTER\r"
expect "CE> "
send -- "touch \$MARKER\r"
expect {close-enough [safe/1]: keep buffer}
send -- "\003"
expect "CE> "
send -- "test ! -e \$MARKER && print protected\r"
expect "protected"
expect "CE> "
send -- "exit\r"
expect eof`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("zsh PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("interrupt executed buffered command: %v", err)
	}
}

func TestZshInteractivePTYHintSubmitsCommand(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '1\\thint\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
spawn -noecho zsh -f
expect -re {[%#] $}
send -- "PROMPT='CE> '\r"
expect "CE> "
send -- "source \$ADAPTER\r"
expect "CE> "
send -- "touch \$MARKER\r"
expect {close-enough [safe/1]: keep buffer}
expect "CE> "
send -- "exit\r"
expect eof`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("zsh PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("hint did not submit buffered command: %v\n%s", err, output)
	}
}

func TestBashInitializationIsGuarded(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	guard := `if [ -z "${_CLOSE_ENOUGH_BASH_LOADED+x}" ]; then`
	marker := "_CLOSE_ENOUGH_BASH_LOADED=1"
	if !strings.HasPrefix(script, "# close-enough bash integration\n"+guard+"\n"+marker) || !strings.HasSuffix(strings.TrimSpace(script), "fi") || strings.Count(script, `bind -x '"\C-m":_close_enough_accept_line'`) != 1 || strings.Count(script, "trap _close_enough_debug DEBUG") != 1 {
		t.Fatalf("bash script lacks an enclosing idempotence guard: %q", script)
	}
}

func TestBashPreExecutionUsesCapturedBuffer(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	capture := `command="$READLINE_LINE"`
	check := `--stage pre --format record --command "$command"`
	if strings.Index(script, capture) < 0 || strings.Index(script, check) < strings.Index(script, capture) || strings.Contains(script, `--command "$READLINE_LINE"`) {
		t.Fatalf("bash pre-execution check does not use a captured buffer: %q", script)
	}
}

func TestBashHintRenderingDoesNotAlterBuffer(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	hint := `if [ "$action" = hint ]; then`
	interrupt := `if [ "$action" = interrupt ]; then`
	start, end := strings.Index(script, hint), strings.Index(script, interrupt)
	if start < 0 || end < start || !strings.Contains(script[start:end], "printf") || !strings.Contains(script[start:end], "return") || strings.Contains(script[start:end], "READLINE_LINE=") {
		t.Fatalf("bash hint path is not non-blocking: %q", script)
	}
}

func TestBashInterruptReplacesBufferWithNoopBeforeReturning(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	interrupt := `if [ "$action" = interrupt ]; then`
	start := strings.Index(script, interrupt)
	if start < 0 || !strings.Contains(script[start:], "READLINE_LINE=':'\n    return 1") {
		t.Fatalf("bash interrupt path does not suppress command execution: %q", script)
	}
}

func TestBashRewriteRequiresSafeNonemptySuggestion(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	rewrite := `if [ "$action" = rewrite ]; then`
	hint := `if [ "$action" = hint ]; then`
	start, end := strings.Index(script, rewrite), strings.Index(script, hint)
	if start < 0 || end < start || !strings.Contains(script[start:end], `[ "$risk" != safe ] || [ -z "$suggestion" ]`) || !strings.Contains(script[start:end], "refused unsafe rewrite") || !strings.Contains(script[start:end], `READLINE_LINE="$suggestion"`) {
		t.Fatalf("bash rewrite path does not fail closed: %q", script)
	}
}

func TestBashPostFailureConsumesCapturedCommand(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	prompt := "_close_enough_prompt() {"
	start := strings.Index(script, prompt)
	if start < 0 {
		t.Fatalf("bash post-failure prompt hook is missing: %q", script)
	}
	branch := script[start:]
	consume := "_close_enough_last_command=''"
	trigger := `daemon request --operation post-failure --shell bash --session "$$" --format record --command "$command"`
	if !strings.Contains(script, "_close_enough_debug() { _close_enough_last_command=$BASH_COMMAND; }") || !strings.Contains(branch, `local status=$? command="$_close_enough_last_command"`) || !strings.Contains(branch, consume) || !strings.Contains(branch, trigger) || strings.Contains(branch, "close-enough check --stage post") || strings.Index(branch, consume) > strings.Index(branch, trigger) {
		t.Fatalf("bash post-failure hook does not consume command safely: %q", branch)
	}
}

func TestBashUsesDaemonForPreAndPostDecisions(t *testing.T) {
	contract, err := ContractFor("bash")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(contract.Configuration, []Configuration{ModeConfiguration, DisplayConfiguration}) {
		t.Fatalf("bash configuration contract = %#v", contract.Configuration)
	}
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, "daemon request --operation pre-send --shell bash") || !strings.Contains(script, "daemon request --operation post-failure --shell bash") {
		t.Fatalf("bash script does not delegate both stages to the daemon: %q", script)
	}
}

func TestBashHandshakeFailsOpen(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	handshake := "_close_enough_handshake() {"
	check := "_close_enough_accept_line() {"
	handshakeStart, checkStart := strings.Index(script, handshake), strings.Index(script, check)
	if handshakeStart < 0 || checkStart < handshakeStart {
		t.Fatalf("bash handshake is missing: %q", script)
	}
	handshakeBody := script[handshakeStart:checkStart]
	if !strings.Contains(handshakeBody, `daemon request --operation handshake --shell bash --session "$$" --ensure=true --format record`) || !strings.Contains(handshakeBody, `[ "${#fields[@]}" -ge 2 ] || return 1`) || !strings.Contains(handshakeBody, `[ "$version" = 1 ] && [ "$action" = ready ] || return 1`) || !strings.Contains(handshakeBody, "_close_enough_daemon_ready=1") {
		t.Fatalf("bash handshake contract = %q", handshakeBody)
	}
	checkEnd := strings.Index(script[checkStart:], "_close_enough_enter_binding=")
	if checkEnd < 0 {
		t.Fatalf("bash accept-line function is unterminated: %q", script)
	}
	checkBody := script[checkStart : checkStart+checkEnd]
	if !strings.Contains(checkBody, "_close_enough_handshake || return") || !strings.Contains(checkBody, `--operation pre-send --shell bash --session "$$" --ensure=false --format record`) || !strings.Contains(checkBody, "_close_enough_daemon_ready=0;") || !strings.Contains(checkBody, "_close_enough_pending_confirmation=''; return") {
		t.Fatalf("bash handshake fallback = %q", checkBody)
	}
}

func TestBashProtocolDecodingPreservesEmptyFields(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `if base64 --decode </dev/null >/dev/null 2>&1; then`) || !strings.Contains(script, `printf %s "$1" | base64 --decode`) || !strings.Contains(script, `separator=$'\034'`) || !strings.Contains(script, `record="${record//$'\t'/$separator}"`) || !strings.Contains(script, `IFS="$separator" read -r -a fields <<< "$record"`) || !strings.Contains(script, `[ "${#fields[@]}" -eq 7 ] || return`) || !strings.Contains(script, `suggestion="$(_close_enough_decode "$suggestion")" || return`) {
		t.Fatalf("bash protocol decoder is not binary-safe and fixed-field: %q", script)
	}
}

func FuzzBashProtocolDecoderMalformedRecords(f *testing.F) {
	for _, record := range []string{"", "1", "1\thint", "1\thint\tsafe\t1\t\t\t%", "2\thint\tsafe\t1\t\t\taGVsbG8", "1\thint\tsafe\t1\t\t\taGVsbG8\textra", "1\trewrite\tsafe\t1\t\t\t%"} {
		f.Add(record)
	}
	bash, err := exec.LookPath("bash")
	if err != nil {
		f.Skip("bash unavailable")
	}
	directory := f.TempDir()
	script, err := Script("bash")
	if err != nil {
		f.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.bash")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		f.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$RECORD\"\n"), 0o700); err != nil {
		f.Fatal(err)
	}
	f.Fuzz(func(t *testing.T, record string) {
		if len(record) > 4<<10 || strings.ContainsRune(record, 0) || !malformedBashProtocolRecord(record) {
			t.Skip()
		}
		result := filepath.Join(directory, "result")
		marker := filepath.Join(directory, "marker")
		input := `$(touch "$MARKER")`
		harness := `source "$1"; READLINE_LINE="$2"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$RESULT"`
		command := exec.Command(bash, "--noprofile", "--norc", "-c", harness, "bash", adapter, input)
		command.Env = append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "MARKER="+marker, "RECORD="+record, "RESULT="+result)
		if output, err := command.CombinedOutput(); err != nil {
			t.Fatalf("bash decoder: %v\n%s", err, output)
		}
		if _, err := os.Stat(marker); !os.IsNotExist(err) {
			t.Fatalf("decoder evaluated input: %v", err)
		}
		buffer, err := os.ReadFile(result)
		if err != nil || string(buffer) != input {
			t.Fatalf("buffer = %q, %v; want %q", buffer, err, input)
		}
	})
}

func malformedBashProtocolRecord(record string) bool {
	if strings.ContainsAny(record, "\r\n") {
		return true
	}
	fields := strings.Split(record, "\t")
	if len(fields) != 7 || fields[0] != "1" {
		return true
	}
	switch fields[1] {
	case "none":
		return false
	case "hint", "interrupt", "rewrite":
	default:
		return true
	}
	if _, err := base64.RawStdEncoding.DecodeString(fields[6]); err == nil {
		return false
	}
	_, err := base64.StdEncoding.DecodeString(fields[6])
	return err != nil
}

func TestBashEnterBindingIsCollisionSafeAndRestorable(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `bind -p 2>/dev/null | command grep '^"\\C-m": '`) || !strings.Contains(script, `[ "$binding" = '"\C-m": accept-line' ] || return 0`) || !strings.Contains(script, `bind -x '"\C-m":_close_enough_accept_line'`) || !strings.Contains(script, `bind -X 2>/dev/null | command grep -F '"\C-m": _close_enough_accept_line' >/dev/null || return 0`) || !strings.Contains(script, `bind '"\C-m": accept-line'`) {
		t.Fatalf("bash Enter binding is not collision-safe and restorable: %q", script)
	}
}

func TestBashRestoresPreexistingEnterBinding(t *testing.T) {
	bash, err := exec.LookPath("bash")
	if err != nil {
		t.Skip("bash unavailable")
	}
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	adapter := filepath.Join(directory, "adapter.bash")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "bindings")
	harness := `current=accept-line; bind() { case "$1" in -p) printf '"\C-m": %s\n' "$current" ;; -x) current=_close_enough_accept_line; printf '%s\n' "$current" >> "$CAPTURE" ;; -X) test "$current" = _close_enough_accept_line && printf '"\C-m": _close_enough_accept_line\n' ;; *) current=accept-line; printf '%s\n' "$current" >> "$CAPTURE" ;; esac; }; source "$1"; _close_enough_restore_enter; printf '%s\n' "$current"`
	command := exec.Command(bash, "--noprofile", "--norc", "-c", harness, "bash", adapter)
	command.Env = append(os.Environ(), "CAPTURE="+capture)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("bash harness: %v\n%s", err, output)
	}
	if got := string(output); got != "accept-line\n" {
		t.Fatalf("restored binding = %q", got)
	}
	bindings, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(bindings); got != "_close_enough_accept_line\naccept-line\n" {
		t.Fatalf("binding changes = %q", got)
	}
}

func TestBashAdapterDoesNotEvaluateCommandOrRewritePayloads(t *testing.T) {
	bash, err := exec.LookPath("bash")
	if err != nil {
		t.Skip("bash unavailable")
	}
	directory := t.TempDir()
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.bash")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '%s\\n' \"$RECORD\" ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct{ name, input, action, want string }{
		{name: "command", input: `$(touch "$MARKER") ; echo injected`, action: "hint", want: `$(touch "$MARKER") ; echo injected`},
		{name: "rewrite", input: "gti", action: "rewrite", want: `$(touch "$MARKER")`},
	} {
		t.Run(test.name, func(t *testing.T) {
			capture, result, marker := filepath.Join(directory, test.name+"-arguments"), filepath.Join(directory, test.name+"-buffer"), filepath.Join(directory, test.name+"-marker")
			payload := test.input
			if test.name == "rewrite" {
				payload = test.want
			}
			record := "1\t" + test.action + "\tsafe\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte(payload))
			harness := `source "$1"; READLINE_LINE="$2"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$RESULT"`
			command := exec.Command(bash, "--noprofile", "--norc", "-c", harness, "bash", adapter, test.input)
			command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "RESULT="+result, "RECORD="+record, "MARKER="+marker)
			if output, err := command.CombinedOutput(); err != nil {
				t.Fatalf("bash harness: %v\n%s", err, output)
			}
			if _, err := os.Stat(marker); !os.IsNotExist(err) {
				t.Fatalf("adapter evaluated payload: %v", err)
			}
			buffer, err := os.ReadFile(result)
			if err != nil || string(buffer) != test.want {
				t.Fatalf("buffer = %q, %v; want %q", buffer, err, test.want)
			}
			if test.name == "command" {
				arguments, err := os.ReadFile(capture)
				if err != nil || !strings.Contains(string(arguments), test.input) {
					t.Fatalf("checker arguments = %q, %v", arguments, err)
				}
			}
		})
	}
}

func TestBashSafeRewriteSubmitsOnSecondEnter(t *testing.T) {
	bash, err := exec.LookPath("bash")
	if err != nil {
		t.Skip("bash unavailable")
	}
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	adapter := filepath.Join(directory, "adapter.bash")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '%s\\n' \"$RECORD\" ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "calls")
	record := "1\trewrite\tsafe\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte("git status"))
	harness := `source "$1"; READLINE_LINE=gti; _close_enough_accept_line; first=$?; first_line="$READLINE_LINE"; _close_enough_accept_line; second=$?; printf '%s|%s|%s|%s\n' "$first" "$first_line" "$second" "$READLINE_LINE"`
	command := exec.Command(bash, "--noprofile", "--norc", "-c", harness, "bash", adapter)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "RECORD="+record)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("bash harness: %v\n%s", err, output)
	}
	if got := string(output); !strings.HasSuffix(got, "1|git status|0|git status\n") {
		t.Fatalf("rewrite flow = %q", got)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "daemon request"); got != 2 {
		t.Fatalf("daemon requests = %d, want 2: %q", got, calls)
	}
}

func TestBashHighRiskConfirmationSubmitsOnSecondEnter(t *testing.T) {
	bash, err := exec.LookPath("bash")
	if err != nil {
		t.Skip("bash unavailable")
	}
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	adapter := filepath.Join(directory, "adapter.bash")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *\"--operation pre-send\"*) count=0; test -f \"$STATE\" && count=$(cat \"$STATE\"); if test \"$count\" = 0; then printf '1\\tinterrupt\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; printf 1 > \"$STATE\"; else printf '1\\tsubmit\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; fi ;; *) exit 1 ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "calls")
	state := filepath.Join(directory, "state")
	suggestion := base64.StdEncoding.EncodeToString([]byte("git push --force"))
	harness := `source "$1"; READLINE_LINE='git push --force'; _close_enough_accept_line; first=$?; first_line="$READLINE_LINE"; _close_enough_accept_line; second=$?; printf '%s|%s|%s|%s\n' "$first" "$first_line" "$second" "$READLINE_LINE"`
	command := exec.Command(bash, "--noprofile", "--norc", "-c", harness, "bash", adapter)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "STATE="+state, "SUGGESTION="+suggestion)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("bash harness: %v\n%s", err, output)
	}
	if got := string(output); !strings.HasSuffix(got, "1|git push --force|0|git push --force\n") {
		t.Fatalf("confirmation flow = %q", got)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "daemon request"); got != 3 {
		t.Fatalf("daemon requests = %d, want 3: %q", got, calls)
	}
}

func TestBashInteractivePTYInterruptPreventsExecution(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.bash")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '1\\tinterrupt\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
spawn -noecho bash --noprofile --norc -i
expect -re {bash-[^#]+\$ }
send -- "PS1='CE> '; PROMPT_COMMAND=\r"
expect "CE> "
send -- "source \$ADAPTER\r"
expect "CE> "
send -- "touch \$MARKER\r"
expect {close-enough [safe/1]: keep buffer}
expect "CE> "
send -- "exit\r"
expect eof`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("bash PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("interrupt executed buffered command: %v", err)
	}
}

func TestFishInitializationIsGuarded(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	guard := "if not set -q _CLOSE_ENOUGH_FISH_LOADED\n  set -g _CLOSE_ENOUGH_FISH_LOADED 1"
	if !strings.HasPrefix(script, "# close-enough fish integration\n"+guard) || !strings.HasSuffix(strings.TrimSpace(script), "end") || strings.Count(script, "bind \\r _close_enough_accept_line") != 1 {
		t.Fatalf("fish script lacks an enclosing idempotence guard: %q", script)
	}
}

func TestFishPreExecutionUsesCapturedBuffer(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	capture := "set -l command (commandline -b)"
	check := `--stage pre --format record --command "$command"`
	if strings.Index(script, capture) < 0 || strings.Index(script, check) < strings.Index(script, capture) || strings.Contains(script, "--command (commandline -b)") {
		t.Fatalf("fish pre-execution check does not use a captured buffer: %q", script)
	}
}

func TestFishHintRenderingDoesNotSuppressExecution(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	hint := `if test "$fields[2]" = hint`
	interrupt := `if test "$fields[2]" = interrupt`
	start, end := strings.Index(script, hint), strings.Index(script, interrupt)
	if start < 0 || end < start || !strings.Contains(script[start:end], "echo ") || !strings.Contains(script[start:end], "commandline -f execute\n    return") {
		t.Fatalf("fish hint path is not non-blocking: %q", script)
	}
}

func TestFishRewriteRequiresSafeNonemptySuggestion(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	rewrite := `if test "$fields[2]" = rewrite`
	hint := `if test "$fields[2]" = hint`
	start, end := strings.Index(script, rewrite), strings.Index(script, hint)
	if start < 0 || end < start || !strings.Contains(script[start:end], `test "$fields[3]" != safe; or test -z "$suggestion"`) || !strings.Contains(script[start:end], "refused unsafe rewrite") || !strings.Contains(script[start:end], `commandline -r "$suggestion"`) {
		t.Fatalf("fish rewrite path does not fail closed: %q", script)
	}
}

func TestFishPostFailureTriggersDiagnostic(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	hook := "function _close_enough_post_failure --on-event fish_postexec"
	start := strings.Index(script, hook)
	if start < 0 || !strings.Contains(script[start:], "set -l command_status $status") || !strings.Contains(script[start:], "set -l command $argv[1]") || !strings.Contains(script[start:], `if test -z "$command"`) || !strings.Contains(script[start:], `if test $command_status -ne 0`) || !strings.Contains(script[start:], `daemon request --operation post-failure --shell fish --session "$fish_pid" --format record --command "$command"`) || strings.Contains(script[start:], "close-enough check --stage post") {
		t.Fatalf("fish post-failure hook is missing or unsafe: %q", script)
	}
}

func TestFishUsesDaemonForPreAndPostDecisions(t *testing.T) {
	contract, err := ContractFor("fish")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(contract.Configuration, []Configuration{ModeConfiguration, DisplayConfiguration}) {
		t.Fatalf("fish configuration contract = %#v", contract.Configuration)
	}
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, "daemon request --operation pre-send --shell fish") || !strings.Contains(script, "daemon request --operation post-failure --shell fish") {
		t.Fatalf("fish script does not delegate both stages to the daemon: %q", script)
	}
}

func TestFishHandshakeFailsOpen(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	handshake := "function _close_enough_handshake"
	check := "function _close_enough_accept_line"
	handshakeStart, checkStart := strings.Index(script, handshake), strings.Index(script, check)
	if handshakeStart < 0 || checkStart < handshakeStart {
		t.Fatalf("fish handshake is missing: %q", script)
	}
	handshakeBody := script[handshakeStart:checkStart]
	if !strings.Contains(handshakeBody, `daemon request --operation handshake --shell fish --session "$fish_pid" --ensure=true --format record`) || !strings.Contains(handshakeBody, `if test (count $fields) -lt 2`) || !strings.Contains(handshakeBody, `if test "$fields[1]" != 1; or test "$fields[2]" != ready`) || !strings.Contains(handshakeBody, "set -g _CLOSE_ENOUGH_DAEMON_READY 1") {
		t.Fatalf("fish handshake contract = %q", handshakeBody)
	}
	checkEnd := strings.Index(script[checkStart:], "function _close_enough_bind_enter")
	if checkEnd < 0 {
		t.Fatalf("fish accept-line function is unterminated: %q", script)
	}
	checkBody := script[checkStart : checkStart+checkEnd]
	if !strings.Contains(checkBody, "_close_enough_handshake; or return") || !strings.Contains(checkBody, `--operation pre-send --shell fish --session "$fish_pid" --ensure=false --format record`) || !strings.Contains(checkBody, "set -g _CLOSE_ENOUGH_DAEMON_READY 0") {
		t.Fatalf("fish handshake fallback = %q", checkBody)
	}
}

func TestFishProtocolDecodingValidatesFixedFields(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `function _close_enough_decode`) || !strings.Contains(script, `if base64 --decode </dev/null >/dev/null 2>&1`) || !strings.Contains(script, `printf '%s' "$argv[1]" | base64`) || !strings.Contains(script, "if test (count $fields) -ne 7") || !strings.Contains(script, `set -l suggestion (_close_enough_decode "$fields[7]")`) || !strings.Contains(script, "or return") {
		t.Fatalf("fish protocol decoder is not binary-safe and fixed-field: %q", script)
	}
}

func TestFishEnterBindingIsCollisionSafeAndRestorable(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `set -l binding (bind \r)`) || !strings.Contains(script, `test "$binding" != "bind --preset enter execute"`) || !strings.Contains(script, `bind \r _close_enough_accept_line`) || !strings.Contains(script, `string match -q "* _close_enough_accept_line" -- (bind \r)`) || !strings.Contains(script, `bind --erase \r`) {
		t.Fatalf("fish Enter binding is not collision-safe and restorable: %q", script)
	}
}

func TestFishAdapterDoesNotEvaluateCommandOrRewritePayloads(t *testing.T) {
	fish, err := exec.LookPath("fish")
	if err != nil {
		t.Skip("fish unavailable")
	}
	directory := t.TempDir()
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.fish")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '%s\\n' \"$RECORD\" ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct{ name, input, action, want string }{
		{name: "command", input: `$(touch "$MARKER") ; echo injected`, action: "hint", want: `$(touch "$MARKER") ; echo injected`},
		{name: "rewrite", input: "gti", action: "rewrite", want: `$(touch "$MARKER")`},
	} {
		t.Run(test.name, func(t *testing.T) {
			capture, result, marker := filepath.Join(directory, test.name+"-arguments"), filepath.Join(directory, test.name+"-buffer"), filepath.Join(directory, test.name+"-marker")
			payload := test.input
			if test.name == "rewrite" {
				payload = test.want
			}
			record := "1\t" + test.action + "\tsafe\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte(payload))
			harness := `function bind; if test (count $argv) -eq 1; echo "bind --preset enter execute"; end; end; function commandline; if test "$argv[1]" = -b; printf '%s' "$BUFFER"; else if test "$argv[1]" = -r; set -g BUFFER "$argv[2]"; end; end; source "$argv[1]"; set -g BUFFER "$argv[2]"; _close_enough_accept_line; printf '%s' "$BUFFER" > "$RESULT"`
			command := exec.Command(fish, "-c", harness, adapter, test.input)
			command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "RESULT="+result, "RECORD="+record, "MARKER="+marker)
			if output, err := command.CombinedOutput(); err != nil {
				t.Fatalf("fish harness: %v\n%s", err, output)
			}
			if _, err := os.Stat(marker); !os.IsNotExist(err) {
				t.Fatalf("adapter evaluated payload: %v", err)
			}
			buffer, err := os.ReadFile(result)
			if err != nil || string(buffer) != test.want {
				t.Fatalf("buffer = %q, %v; want %q", buffer, err, test.want)
			}
			if test.name == "command" {
				arguments, err := os.ReadFile(capture)
				if err != nil || !strings.Contains(string(arguments), test.input) {
					t.Fatalf("checker arguments = %q, %v", arguments, err)
				}
			}
		})
	}
}

func TestFishSafeRewriteSubmitsOnSecondEnter(t *testing.T) {
	fish, err := exec.LookPath("fish")
	if err != nil {
		t.Skip("fish unavailable")
	}
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	adapter := filepath.Join(directory, "adapter.fish")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '%s\\n' \"$RECORD\" ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "calls")
	record := "1\trewrite\tsafe\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte("git status"))
	harness := `function bind; if test (count $argv) -eq 1; echo "bind --preset enter execute"; end; end; function commandline; if test "$argv[1]" = -b; printf '%s' "$BUFFER"; else if test "$argv[1]" = -r; set -g BUFFER "$argv[2]"; else if test "$argv[1]" = -f; and test "$argv[2]" = execute; set -g EXECUTE_COUNT (math $EXECUTE_COUNT + 1); end; end; source "$argv[1]"; set -g BUFFER gti; set -g EXECUTE_COUNT 0; _close_enough_accept_line; _close_enough_accept_line; printf '%s|%s\n' "$BUFFER" "$EXECUTE_COUNT"`
	command := exec.Command(fish, "-c", harness, adapter)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "RECORD="+record)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("fish harness: %v\n%s", err, output)
	}
	if got := string(output); !strings.HasSuffix(got, "git status|1\n") {
		t.Fatalf("rewrite flow = %q", got)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "daemon request"); got != 2 {
		t.Fatalf("daemon requests = %d, want 2: %q", got, calls)
	}
}

func TestFishHighRiskConfirmationSubmitsOnSecondEnter(t *testing.T) {
	fish, err := exec.LookPath("fish")
	if err != nil {
		t.Skip("fish unavailable")
	}
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	adapter := filepath.Join(directory, "adapter.fish")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *\"--operation pre-send\"*) count=0; test -f \"$STATE\" && count=$(cat \"$STATE\"); if test \"$count\" = 0; then printf '1\\tinterrupt\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; printf 1 > \"$STATE\"; else printf '1\\tsubmit\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; fi ;; *) exit 1 ;; esac\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	capture := filepath.Join(directory, "calls")
	state := filepath.Join(directory, "state")
	suggestion := base64.StdEncoding.EncodeToString([]byte("git push --force"))
	harness := `function bind; if test (count $argv) -eq 1; echo "bind --preset enter execute"; end; end; function commandline; if test "$argv[1]" = -b; printf '%s' "$BUFFER"; else if test "$argv[1]" = -f; and test "$argv[2]" = execute; set -g EXECUTE_COUNT (math $EXECUTE_COUNT + 1); end; end; source "$argv[1]"; set -g BUFFER 'git push --force'; set -g EXECUTE_COUNT 0; _close_enough_accept_line; _close_enough_accept_line; printf '%s|%s\n' "$BUFFER" "$EXECUTE_COUNT"`
	command := exec.Command(fish, "-c", harness, adapter)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "CAPTURE="+capture, "STATE="+state, "SUGGESTION="+suggestion)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("fish harness: %v\n%s", err, output)
	}
	if got := string(output); !strings.HasSuffix(got, "git push --force|1\n") {
		t.Fatalf("confirmation flow = %q", got)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "daemon request"); got != 3 {
		t.Fatalf("daemon requests = %d, want 3: %q", got, calls)
	}
}

func TestFishInteractivePTYInterruptPreventsExecution(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.fish")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '1\\tinterrupt\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
proc expect_text {text} {
  expect {
    -exact $text {}
    timeout { puts stderr "timed out waiting for: $text"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $text"; exit 1 }
  }
}
proc expect_regex {pattern} {
  expect {
    -re $pattern {}
    timeout { puts stderr "timed out waiting for: $pattern"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $pattern"; exit 1 }
  }
}
spawn -noecho env TERM=dumb fish --no-config
expect_regex {> }
send -- "function fish_prompt; echo -n 'CE> '; end\r"
expect_text "function fish_prompt; echo -n 'CE> '; end\r\n"
expect_text {CE> }
send -- "source \$ADAPTER\r"
expect_text "source \$ADAPTER\r\n"
expect_text {CE> }
send -- "touch \$MARKER\r"
expect_text {close-enough [safe/1]: keep buffer}
close`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("fish PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("interrupt executed buffered command: %v", err)
	}
}

func TestFishInteractivePTYHintSubmitsCommand(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.fish")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	checked := filepath.Join(directory, "checked")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ntouch "+strconv.Quote(checked)+"\nprintf '1\\thint\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
proc expect_text {text} {
  expect {
    -exact $text {}
    timeout { puts stderr "timed out waiting for: $text"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $text"; exit 1 }
  }
}
proc expect_regex {pattern} {
  expect {
    -re $pattern {}
    timeout { puts stderr "timed out waiting for: $pattern"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $pattern"; exit 1 }
  }
}
spawn -noecho env TERM=dumb fish --no-config
expect_regex {> }
send -- "function fish_prompt; echo -n 'CE> '; end\r"
expect_text "function fish_prompt; echo -n 'CE> '; end\r\n"
expect_text {CE> }
send -- "source \$ADAPTER\r"
expect_text "source \$ADAPTER\r\n"
expect_text {CE> }
send -- "touch \$MARKER\r"
expect_text "touch \$MARKER\r\n"
expect_text {CE> }
if {![file exists $env(CHECKED)]} {
  puts stderr "checker did not run"
  exit 1
}
send -- "exit\r"
expect {
  eof {}
  timeout { puts stderr "timed out waiting for EOF"; exit 1 }
}`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker, "CHECKED="+checked)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("fish PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("hint did not submit buffered command: %v\n%s", err, output)
	}
	if _, err := os.Stat(checked); err != nil {
		t.Fatalf("hint did not invoke checker: %v\n%s", err, output)
	}
}

func TestPowerShellInitializationIsGuarded(t *testing.T) {
	script, err := Script("powershell")
	if err != nil {
		t.Fatal(err)
	}
	guard := "if (-not $global:CloseEnoughAdapterLoaded) {\n$global:CloseEnoughAdapterLoaded = $true"
	if !strings.HasPrefix(script, "# close-enough PowerShell integration\n"+guard) || !strings.HasSuffix(strings.TrimSpace(script), "}") || strings.Count(script, "Set-PSReadLineKeyHandler -Key Enter -ScriptBlock") != 1 {
		t.Fatalf("PowerShell script lacks an enclosing idempotence guard: %q", script)
	}
}

func TestPowerShellPreExecutionUsesCapturedBuffer(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	capture := "$command = $line"
	check := "--stage pre --format json --command $command"
	if strings.Index(script, capture) < 0 || strings.Index(script, check) < strings.Index(script, capture) || strings.Contains(script, "--command $line") {
		t.Fatalf("PowerShell pre-execution check does not use a captured buffer: %q", script)
	}
}

func TestPowerShellHintRenderingDoesNotSuppressSubmission(t *testing.T) {
	script, err := Script("powershell")
	if err != nil {
		t.Fatal(err)
	}
	hint := "if ($decision.action -eq 'hint') {"
	interrupt := "if ($decision.action -eq 'interrupt') {"
	start, end := strings.Index(script, hint), strings.Index(script, interrupt)
	if start < 0 || end < start || !strings.Contains(script[start:end], "Write-Host") || !strings.Contains(script[start:end], "AcceptLine()") || !strings.Contains(script[start:end], "return") {
		t.Fatalf("PowerShell hint path is not non-blocking: %q", script)
	}
}

func TestPowerShellInterruptReturnsBeforeCommandExecution(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	interrupt := "if ($decision.action -eq 'interrupt') {"
	start := strings.Index(script, interrupt)
	if start < 0 || !strings.Contains(script[start:], "Write-Host") || !strings.Contains(script[start:], "return") {
		t.Fatalf("PowerShell interrupt path does not suppress command submission: %q", script)
	}
}

func TestPowerShellRewriteRequiresSafeNonemptySuggestion(t *testing.T) {
	script, err := Script("powershell")
	if err != nil {
		t.Fatal(err)
	}
	rewrite := "if ($decision.action -eq 'rewrite') {"
	hint := "if ($decision.action -eq 'hint') {"
	start, end := strings.Index(script, rewrite), strings.Index(script, hint)
	if start < 0 || end < start || !strings.Contains(script[start:end], "$decision.risk -ne 'safe'") || !strings.Contains(script[start:end], "IsNullOrEmpty($decision.suggestion)") || !strings.Contains(script[start:end], "refused unsafe rewrite") || !strings.Contains(script[start:end], "PSConsoleReadLine]::Replace") {
		t.Fatalf("PowerShell rewrite path does not fail closed: %q", script)
	}
}

func TestPowerShellPostFailureConsumesHistoryEntry(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, "function global:prompt {") || !strings.Contains(script, "$status = $?") || !strings.Contains(script, "$entry = Get-History -Count 1") || !strings.Contains(script, "$entry.Id -ne $global:CloseEnoughLastHistoryId") || !strings.Contains(script, `--stage post --format plain --command $entry.CommandLine`) {
		t.Fatalf("PowerShell post-failure hook is missing or unsafe: %q", script)
	}
}

func TestPowerShellPropagatesModeAndDisplayConfiguration(t *testing.T) {
	contract, err := ContractFor("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(contract.Configuration, []Configuration{ModeConfiguration, DisplayConfiguration}) {
		t.Fatalf("PowerShell configuration contract = %#v", contract.Configuration)
	}
	script, err := Script("powershell")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, "--stage pre --format json") || !strings.Contains(script, "--stage post --format plain") {
		t.Fatalf("PowerShell script does not delegate mode and display configuration: %q", script)
	}
}

func TestPowerShellProtocolDecodingFailsOpenOnMalformedJSON(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `$record = & close-enough check --stage pre --format json --command $command`) || !strings.Contains(script, `$LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($record)`) || !strings.Contains(script, `ConvertFrom-Json -ErrorAction Stop`) || !strings.Contains(script, `catch { return }`) {
		t.Fatalf("PowerShell protocol decoder is not binary-safe and failure-aware: %q", script)
	}
}

func TestPowerShellEnterBindingIsCollisionSafeAndRestorable(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `Get-PSReadLineKeyHandler -Chord Enter`) || !strings.Contains(script, `$global:CloseEnoughPreviousEnterHandler.Function -eq 'AcceptLine'`) || !strings.Contains(script, `Set-PSReadLineKeyHandler -Key Enter -ScriptBlock`) || !strings.Contains(script, `function global:Restore-CloseEnoughEnterHandler`) || !strings.Contains(script, `Set-PSReadLineKeyHandler -Key Enter -Function AcceptLine`) {
		t.Fatalf("PowerShell Enter binding is not collision-safe and restorable: %q", script)
	}
}

func TestPowerShellAdapterDoesNotEvaluatePayloads(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	forbidden := []string{"Invoke-Expression", "iex ", "--command $line", "Replace(0, $line.Length, (&"}
	for _, value := range forbidden {
		if strings.Contains(script, value) {
			t.Fatalf("PowerShell adapter exposes injection primitive %q: %q", value, script)
		}
	}
	for _, value := range []string{"--command $command", "Replace(0, $line.Length, $decision.suggestion)", "--command $entry.CommandLine"} {
		if !strings.Contains(script, value) {
			t.Fatalf("PowerShell adapter lacks quoted payload boundary %q: %q", value, script)
		}
	}
}

func TestPowerShellInteractivePTYLoadsAdapter(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.ps1")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '{\"version\":1,\"action\":\"none\",\"risk\":\"safe\",\"confidence\":0}\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	pty := `set timeout 5
proc expect_text {text} {
  expect {
    -exact $text {}
    timeout { puts stderr "timed out waiting for: $text"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $text"; exit 1 }
  }
}
proc expect_regex {pattern} {
  expect {
    -re $pattern {}
    timeout { puts stderr "timed out waiting for: $pattern"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $pattern"; exit 1 }
  }
}
spawn -noecho env TERM=dumb pwsh -NoLogo -NoProfile
stty rows 24 columns 80 < $spawn_out(slave,name)
expect_before {
  -exact "\033\[6n" { send -- "\033\[24;80R"; exp_continue }
}
expect_regex {PS .*?> }
send -- ". \$env:ADAPTER; Write-Output (\[Text.Encoding\]::UTF8.GetString(\[Convert\]::FromBase64String('Q0VfQURBUFRFUl9SRUFEWQ==')))\r"
expect_text {CE_ADAPTER_READY}
expect_regex {PS .*?> }
send -- "exit\r"
expect {
  eof {}
  timeout { puts stderr "timed out waiting for EOF"; exit 1 }
}`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("PowerShell PTY: %v\n%s", err, output)
	}
}

func TestPowerShellInteractivePTYInterruptPreventsExecution(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.ps1")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '{\"version\":1,\"action\":\"interrupt\",\"risk\":\"safe\",\"confidence\":1,\"suggestion\":\"keep buffer\"}\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
proc expect_text {text} {
  expect {
    -exact $text {}
    timeout { puts stderr "timed out waiting for: $text"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $text"; exit 1 }
  }
}
proc expect_regex {pattern} {
  expect {
    -re $pattern {}
    timeout { puts stderr "timed out waiting for: $pattern"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $pattern"; exit 1 }
  }
}
spawn -noecho env TERM=dumb pwsh -NoLogo -NoProfile
stty rows 24 columns 80 < $spawn_out(slave,name)
expect_before {
  -exact "\033\[6n" { send -- "\033\[24;80R"; exp_continue }
}
expect_regex {PS .*?> }
send -- ". \$env:ADAPTER; Write-Output (\[Text.Encoding\]::UTF8.GetString(\[Convert\]::FromBase64String('Q0VfQURBUFRFUl9SRUFEWQ==')))\r"
expect_text {CE_ADAPTER_READY}
expect_regex {PS .*?> }
send -- "Set-Content -NoNewline -Path \$env:MARKER -Value executed\r"
expect_text {close-enough [safe/1]: keep buffer}
close`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("PowerShell PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("interrupt executed buffered command: %v", err)
	}
}

func TestPowerShellInteractivePTYHintSubmitsCommand(t *testing.T) {
	expect, err := exec.LookPath("expect")
	if err != nil {
		t.Skip("expect unavailable")
	}
	directory := t.TempDir()
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	adapter := filepath.Join(directory, "adapter.ps1")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	checker := filepath.Join(directory, "close-enough")
	checked := filepath.Join(directory, "checked")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ntouch "+strconv.Quote(checked)+"\nprintf '{\"version\":1,\"action\":\"hint\",\"risk\":\"safe\",\"confidence\":1,\"suggestion\":\"keep buffer\"}\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
proc expect_text {text} {
  expect {
    -exact $text {}
    timeout { puts stderr "timed out waiting for: $text"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $text"; exit 1 }
  }
}
proc expect_regex {pattern} {
  expect {
    -re $pattern {}
    timeout { puts stderr "timed out waiting for: $pattern"; exit 1 }
    eof { puts stderr "unexpected EOF waiting for: $pattern"; exit 1 }
  }
}
spawn -noecho env TERM=dumb pwsh -NoLogo -NoProfile
stty rows 24 columns 80 < $spawn_out(slave,name)
expect_before {
  -exact "\033\[6n" { send -- "\033\[24;80R"; exp_continue }
}
expect_regex {PS .*?> }
send -- ". \$env:ADAPTER; Write-Output (\[Text.Encoding\]::UTF8.GetString(\[Convert\]::FromBase64String('Q0VfQURBUFRFUl9SRUFEWQ==')))\r"
expect_text {CE_ADAPTER_READY}
expect_regex {PS .*?> }
send -- "Set-Content -NoNewline -Path \$env:MARKER -Value executed\r"
expect_text {close-enough [safe/1]: keep buffer}
send -- "exit\r"
expect {
  eof {}
  timeout { puts stderr "timed out waiting for EOF"; exit 1 }
}`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("PowerShell PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("hint did not submit buffered command: %v\n%s", err, output)
	}
	if _, err := os.Stat(checked); err != nil {
		t.Fatalf("hint did not invoke checker: %v\n%s", err, output)
	}
}

func TestZshRewriteRequiresSafeNonemptySuggestion(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	rewrite := `if [[ "$action" == rewrite ]]; then`
	hint := `if [[ "$action" == hint ]]; then`
	start, end := strings.Index(script, rewrite), strings.Index(script, hint)
	if start < 0 || end < start {
		t.Fatalf("zsh rewrite branch is missing: %q", script)
	}
	branch := script[start:end]
	if !strings.Contains(branch, `if [[ "$risk" != safe || -z "$suggestion" ]]; then`) || !strings.Contains(branch, "refused unsafe rewrite") || !strings.Contains(branch, "BUFFER=\"$suggestion\"") || strings.Count(branch, "return 1") != 2 {
		t.Fatalf("zsh rewrite branch does not fail closed: %q", branch)
	}
}

func TestZshPostFailureConsumesCapturedCommand(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	preexec := `function _close_enough_preexec { _CLOSE_ENOUGH_LAST_COMMAND="$1"; _CLOSE_ENOUGH_PENDING_REWRITE='' }`
	precmd := "function _close_enough_precmd {"
	preexecStart, precmdStart := strings.Index(script, preexec), strings.Index(script, precmd)
	if preexecStart < 0 || precmdStart < preexecStart {
		t.Fatalf("zsh post-failure hooks are missing: %q", script)
	}
	end := strings.Index(script[precmdStart:], "autoload -Uz add-zsh-hook")
	if end < 0 {
		t.Fatalf("zsh precmd hook is unterminated: %q", script)
	}
	branch := script[precmdStart : precmdStart+end]
	consume := "_CLOSE_ENOUGH_LAST_COMMAND=''"
	trigger := `daemon request --operation post-failure --shell zsh --session "$$" --format record --command "$command"`
	if !strings.Contains(branch, `local status=$? command="$_CLOSE_ENOUGH_LAST_COMMAND"`) || !strings.Contains(branch, consume) || !strings.Contains(branch, `[[ -z "$command" ]] && return`) || !strings.Contains(branch, trigger) || strings.Contains(branch, "close-enough check --stage post") || strings.Index(branch, consume) > strings.Index(branch, trigger) {
		t.Fatalf("zsh post-failure trigger does not consume command safely: %q", branch)
	}
}

func TestZshUsesDaemonForPreAndPostDecisions(t *testing.T) {
	contract, err := ContractFor("zsh")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(contract.Configuration, []Configuration{ModeConfiguration, DisplayConfiguration}) {
		t.Fatalf("zsh configuration contract = %#v", contract.Configuration)
	}
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, "daemon request --operation pre-send --shell zsh") || !strings.Contains(script, "daemon request --operation post-failure --shell zsh") {
		t.Fatalf("zsh script does not delegate both stages to the daemon: %q", script)
	}
}

func TestZshHandshakeFailsOpen(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	handshake := "function _close_enough_handshake {"
	check := "function _close_enough_check {"
	handshakeStart, checkStart := strings.Index(script, handshake), strings.Index(script, check)
	if handshakeStart < 0 || checkStart < handshakeStart {
		t.Fatalf("zsh handshake is missing: %q", script)
	}
	handshakeBody := script[handshakeStart:checkStart]
	if !strings.Contains(handshakeBody, `daemon request --operation handshake --shell zsh --session "$$" --ensure=true --format record`) || !strings.Contains(handshakeBody, `[[ "$version" == "1" && "$action" == ready ]] || return 1`) || !strings.Contains(handshakeBody, "_CLOSE_ENOUGH_DAEMON_READY=1") {
		t.Fatalf("zsh handshake contract = %q", handshakeBody)
	}
	checkEnd := strings.Index(script[checkStart:], "function _close_enough_accept_line {")
	if checkEnd < 0 {
		t.Fatalf("zsh check function is unterminated: %q", script)
	}
	checkBody := script[checkStart : checkStart+checkEnd]
	if !strings.Contains(checkBody, "_close_enough_handshake || return 0") || !strings.Contains(checkBody, `--operation pre-send --shell zsh --session "$$" --ensure=false --format record`) || !strings.Contains(checkBody, "_CLOSE_ENOUGH_DAEMON_READY=0; return 0") {
		t.Fatalf("zsh handshake fallback = %q", checkBody)
	}
}

func TestZshProtocolDecodingFailsOpenOnMalformedRecords(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `if base64 --decode </dev/null >/dev/null 2>&1; then`) || !strings.Contains(script, `print -rn -- "$1" | base64 --decode`) || strings.Contains(script, "_close_enough_decode { echo") || !strings.Contains(script, `fields=("${(@ps:\t:)record}")`) || !strings.Contains(script, `(( ${#fields} == 7 )) || return 0`) || !strings.Contains(script, `suggestion="$(_close_enough_decode "$suggestion")" || return 0`) {
		t.Fatalf("zsh protocol decoder is not binary-safe and fail-open: %q", script)
	}
}

func TestContractReturnsIndependentSlices(t *testing.T) {
	first, err := ContractFor("zsh")
	if err != nil {
		t.Fatal(err)
	}
	first.Capabilities[0] = "mutated"
	first.Configuration[0] = "mutated"
	second, err := ContractFor("zsh")
	if err != nil {
		t.Fatal(err)
	}
	if second.Capabilities[0] != PreExecution || second.Configuration[0] != ModeConfiguration {
		t.Fatalf("contract mutation leaked: %#v", second)
	}
}

func TestUnsupportedAdapterFailsClosed(t *testing.T) {
	if _, err := Script("csh"); err == nil {
		t.Fatal("unsupported script succeeded")
	}
	if _, err := ContractFor("csh"); err == nil {
		t.Fatal("unsupported contract succeeded")
	}
	if got := Doctor("/bin/csh", "test"); got.Supported || !slices.Equal(got.Limitations, []string{"unsupported shell"}) || !slices.Equal(got.RemediationHints, []string{"use zsh, bash, fish, or powershell"}) {
		t.Fatalf("unsupported doctor result: %#v", got)
	}
}

func TestDoctorProvidesAdapterRemediationHints(t *testing.T) {
	for _, test := range []struct {
		shell string
		want  []string
	}{
		{"fish", []string{"review custom Enter bindings before initializing the adapter"}},
		{"pwsh", []string{"install or enable PSReadLine, then initialize the adapter again"}},
	} {
		t.Run(test.shell, func(t *testing.T) {
			if got := Doctor("/bin/"+test.shell, "test").RemediationHints; !slices.Equal(got, test.want) {
				t.Fatalf("remediation hints = %#v, want %#v", got, test.want)
			}
		})
	}
	if got := remediationHints([]string{"unknown limitation"}); !slices.Equal(got, []string{"review adapter limitation: unknown limitation"}) {
		t.Fatalf("fallback remediation hint = %#v", got)
	}
}
