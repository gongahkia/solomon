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

type safeRewriteFixture struct {
	Name       string `json:"name"`
	Input      string `json:"input"`
	Suggestion string `json:"suggestion"`
}

type highRiskConfirmationFixture struct {
	Name    string `json:"name"`
	Command string `json:"command"`
}

type rewriteUndoFixture struct {
	Name            string `json:"name"`
	Input           string `json:"input"`
	Suggestion      string `json:"suggestion"`
	UndoOutcome     string `json:"undo_outcome"`
	WantBuffer      string `json:"want_buffer"`
	SubmitAfterUndo bool   `json:"submit_after_undo"`
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
		{"fish", "_CLOSE_ENOUGH_DIAGNOSTIC_COUNT 0", "_close_enough_allow_diagnostic", "_close_enough_allow_suggestion", `if test "$fields[2]" = hint`, `if test "$fields[2]" = interrupt`, "    return\n  end", "daemon request --operation post-failure --shell fish"},
		{"pwsh", "CloseEnoughDiagnosticCount = 0", "Allow-CloseEnoughDiagnostic", "Allow-CloseEnoughSuggestion", "if ($decision.action -eq 'hint')", "if ($decision.action -eq 'interrupt')", "    return\n  }", "daemon request --operation post-failure --shell powershell"},
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

func TestAdaptersAssociateFailuresWithNextManualSuccess(t *testing.T) {
	tests := []struct {
		shell   string
		needles []string
	}{
		{"zsh", []string{"_CLOSE_ENOUGH_PENDING_FAILURE_TOKEN", `_CLOSE_ENOUGH_AUTOMATIC_REWRITE="$command"`, `post-success --shell zsh --session "$$" --token "$token"`, `post-failure --shell zsh --session "$$" --token "$token"`}},
		{"fish", []string{"_CLOSE_ENOUGH_PENDING_FAILURE_TOKEN", "_CLOSE_ENOUGH_AUTOMATIC_REWRITE 1", `post-success --shell fish --session "$fish_pid" --token "$token"`, `post-failure --shell fish --session "$fish_pid" --token "$token"`}},
		{"pwsh", []string{"CloseEnoughPendingFailureToken", "CloseEnoughAutomaticRewrite = $true", "post-success --shell powershell --session $PID --token $token", "post-failure --shell powershell --session $PID --token $token"}},
	}
	for _, test := range tests {
		t.Run(test.shell, func(t *testing.T) {
			script, err := Script(test.shell)
			if err != nil {
				t.Fatal(err)
			}
			for _, needle := range test.needles {
				if !strings.Contains(script, needle) {
					t.Fatalf("script missing failure token lifecycle %q", needle)
				}
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '%s\\n' \"$RECORD\" ;; esac\n"), 0o700); err != nil {
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

func TestZshFailureTokenSurvivesManualSuccess(t *testing.T) {
	zsh, err := exec.LookPath("zsh")
	if err != nil {
		t.Skip("zsh unavailable")
	}
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	adapter := filepath.Join(directory, "adapter.zsh")
	if err := os.WriteFile(adapter, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	calls := filepath.Join(directory, "calls")
	checker := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALLS\"\nprintf '1\\tnone\\t\\t\\t\\t\\t\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	harness := `zle() { :; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; _close_enough_preexec 'git sttaus'; false; _close_enough_precmd; _close_enough_preexec 'git status'; true; _close_enough_precmd; _CLOSE_ENOUGH_PENDING_FAILURE_TOKEN=retained; _CLOSE_ENOUGH_AUTOMATIC_REWRITE='git status'; _close_enough_preexec 'git status'; true; _close_enough_precmd; print -r -- "pending=$_CLOSE_ENOUGH_PENDING_FAILURE_TOKEN"`
	command := exec.Command(zsh, "-fc", harness, "zsh", adapter)
	command.Env = append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "CALLS="+calls)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("zsh failure-token harness: %v: %s", err, output)
	}
	if got := strings.TrimSpace(string(output)); got != "pending=retained" {
		t.Fatalf("automatic rewrite consumed pending token: %q", got)
	}
	data, err := os.ReadFile(calls)
	if err != nil {
		t.Fatalf("read token calls: %v; output %s", err, output)
	}
	var failureToken string
	var successTokens []string
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		fields := strings.Fields(line)
		for index := range fields {
			if fields[index] == "--token" && index+1 < len(fields) {
				if strings.Contains(line, "--operation post-failure") {
					failureToken = fields[index+1]
				}
				if strings.Contains(line, "--operation post-success") {
					successTokens = append(successTokens, fields[index+1])
				}
			}
		}
	}
	if failureToken == "" || len(successTokens) != 2 || successTokens[0] != failureToken || successTokens[1] != "none" {
		t.Fatalf("failure token %q, success tokens %#v, calls %q", failureToken, successTokens, data)
	}
}

func TestAdapterScriptsParse(t *testing.T) {
	tests := []struct {
		shell       string
		interpreter string
		args        func(string) []string
	}{
		{"zsh", "zsh", func(path string) []string { return []string{"-n", path} }},
		{"bash", "bash", func(path string) []string { return []string{"-n", path} }},
		{"fish", "fish", func(path string) []string { return []string{"-n", path} }},
		{"pwsh", "pwsh", func(string) []string {
			return []string{"-NoProfile", "-NonInteractive", "-Command", "[scriptblock]::Create([System.IO.File]::ReadAllText($env:ADAPTER_PATH)) | Out-Null"}
		}},
	}
	for _, test := range tests {
		t.Run(test.shell, func(t *testing.T) {
			interpreter, err := exec.LookPath(test.interpreter)
			if err != nil {
				t.Skipf("%s unavailable", test.interpreter)
			}
			script, err := Script(test.shell)
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(t.TempDir(), "adapter")
			if err := os.WriteFile(path, []byte(script), 0o600); err != nil {
				t.Fatal(err)
			}
			command := exec.Command(interpreter, test.args(path)...)
			command.Env = append(os.Environ(), "ADAPTER_PATH="+path)
			if output, err := command.CombinedOutput(); err != nil {
				t.Fatalf("adapter parse: %v: %s", err, output)
			}
		})
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
	for _, shellName := range []string{"zsh", "fish"} {
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
	checkerScript := "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$CAPTURE\"\noperation= command=\nwhile [ $# -gt 0 ]; do\n  case \"$1\" in\n    --operation|--command) key=$1; shift; test $# -gt 0 || exit 1; case \"$key\" in --operation) operation=$1 ;; --command) command=$1 ;; esac ;;\n  esac\n  shift\ndone\nif [ \"$operation\" = handshake ]; then\n  printf '1\\tready\\t\\t\\t\\t\\t\\n'\nelif [ \"$command\" = \"$COMMAND_INPUT\" ]; then\n  printf '%s\\n' \"$COMMAND_RECORD\"\nelif [ \"$command\" = \"$SAFE_INPUT\" ]; then\n  printf '%s\\n' \"$SAFE_RECORD\"\nelse\n  printf '%s\\n' \"$HIGH_RECORD\"\nfi\n"
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
		harness := `source "$1"; _close_enough_submit_line() { :; }; READLINE_LINE="$2"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$COMMAND_RESULT"; READLINE_LINE="$SAFE_INPUT"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$REWRITE_RESULT"; READLINE_LINE="$HIGH_INPUT"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$HIGH_RISK_RESULT"`
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

func TestSafeRewriteSecondEnterCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/safe_rewrite_second_enter.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []safeRewriteFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("safe rewrite corpus is empty")
	}
	for _, shellName := range []string{"zsh", "fish"} {
		shellPath, err := exec.LookPath(shellName)
		if err != nil {
			t.Run(shellName, func(t *testing.T) { t.Skip(shellName + " unavailable") })
			continue
		}
		for _, fixture := range fixtures {
			t.Run(shellName+"/"+fixture.Name, func(t *testing.T) {
				if fixture.Name == "" || fixture.Input == "" || fixture.Suggestion == "" {
					t.Fatalf("invalid safe rewrite fixture: %#v", fixture)
				}
				runSafeRewriteSecondEnterFixture(t, shellName, shellPath, fixture)
			})
		}
	}
}

func runSafeRewriteSecondEnterFixture(t *testing.T, shellName, shellPath string, fixture safeRewriteFixture) {
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
	checkerScript := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \" $* \" in *\" --operation handshake \"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *\" --operation pre-send \"*) printf '%s\\n' \"$RECORD\" ;; *) exit 1 ;; esac\n"
	if err := os.WriteFile(checker, []byte(checkerScript), 0o700); err != nil {
		t.Fatal(err)
	}
	capture, result := filepath.Join(directory, "calls"), filepath.Join(directory, "result")
	environment := append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "CAPTURE="+capture, "RECORD="+commandInjectionRecord("rewrite", "safe", fixture.Suggestion), "RESULT="+result)
	var command *exec.Cmd
	switch shellName {
	case "zsh":
		harness := `zle() { :; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; BUFFER="$2"; _close_enough_check; first=$?; first_buffer="$BUFFER"; _close_enough_check; second=$?; print -rn -- "$first|$first_buffer|$second|$BUFFER" > "$RESULT"`
		command = exec.Command(shellPath, "-fc", harness, "zsh", adapter, fixture.Input)
	case "bash":
		harness := `source "$1"; _close_enough_submit_line() { :; }; READLINE_LINE="$2"; _close_enough_accept_line; first=$?; first_buffer="$READLINE_LINE"; _close_enough_accept_line; second=$?; printf '%s' "$first|$first_buffer|$second|$READLINE_LINE" > "$RESULT"`
		command = exec.Command(shellPath, "--noprofile", "--norc", "-c", harness, "bash", adapter, fixture.Input)
	case "fish":
		harness := `set -g EXECUTES 0; function bind; if test (count $argv) -eq 1; echo "bind --preset enter execute"; end; end; function commandline; if test "$argv[1]" = -b; printf '%s' "$BUFFER"; else if test "$argv[1]" = -r; set -g BUFFER "$argv[2]"; else if test "$argv[1]" = -f; and test "$argv[2]" = execute; set -g EXECUTES (math $EXECUTES + 1); end; end; source "$argv[1]"; set -g BUFFER "$argv[2]"; _close_enough_accept_line; set -g FIRST_BUFFER "$BUFFER"; _close_enough_accept_line; printf '%s' "$FIRST_BUFFER|$BUFFER|$EXECUTES" > "$RESULT"`
		command = exec.Command(shellPath, "-c", harness, adapter, fixture.Input)
	default:
		t.Fatalf("unsupported shell %q", shellName)
	}
	command.Env = environment
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("%s harness: %v\n%s", shellName, err, output)
	}
	data, err := os.ReadFile(result)
	if err != nil {
		t.Fatal(err)
	}
	if shellName == "fish" {
		if got, want := string(data), fixture.Suggestion+"|"+fixture.Suggestion+"|1"; got != want {
			t.Fatalf("rewrite flow = %q, want %q", got, want)
		}
	} else if got, want := string(data), "1|"+fixture.Suggestion+"|0|"+fixture.Suggestion; got != want {
		t.Fatalf("rewrite flow = %q, want %q", got, want)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "--operation"); got != 2 || strings.Count(string(calls), "--operation pre-send") != 1 || !strings.Contains(string(calls), fixture.Input) {
		t.Fatalf("daemon calls = %q", calls)
	}
}

func TestRewriteUndoCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/rewrite_undo.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []rewriteUndoFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("rewrite undo corpus is empty")
	}
	seenNames := make(map[string]struct{}, len(fixtures))
	for _, fixture := range fixtures {
		if _, exists := seenNames[fixture.Name]; exists {
			t.Fatalf("duplicate rewrite undo fixture name %q", fixture.Name)
		}
		seenNames[fixture.Name] = struct{}{}
	}
	for _, shellName := range []string{"zsh", "fish"} {
		shellPath, err := exec.LookPath(shellName)
		if err != nil {
			t.Run(shellName, func(t *testing.T) { t.Skip(shellName + " unavailable") })
			continue
		}
		for _, fixture := range fixtures {
			t.Run(shellName+"/"+fixture.Name, func(t *testing.T) {
				if fixture.Name == "" || fixture.Input == "" || fixture.Suggestion == "" || fixture.WantBuffer == "" {
					t.Fatalf("invalid rewrite undo fixture: %#v", fixture)
				}
				switch fixture.UndoOutcome {
				case "restore":
					if fixture.SubmitAfterUndo || fixture.WantBuffer != fixture.Input {
						t.Fatalf("restore fixture = %#v", fixture)
					}
				case "expired", "malformed", "unavailable":
					if !fixture.SubmitAfterUndo || fixture.WantBuffer != fixture.Suggestion {
						t.Fatalf("fail-open fixture = %#v", fixture)
					}
				default:
					t.Fatalf("unsupported undo outcome %q", fixture.UndoOutcome)
				}
				runRewriteUndoFixture(t, shellName, shellPath, fixture)
			})
		}
	}
}

func runRewriteUndoFixture(t *testing.T, shellName, shellPath string, fixture rewriteUndoFixture) {
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
	const token = "undo-token"
	rewrite := "1\trewrite\tsafe\t1\t\t\t" + base64.StdEncoding.EncodeToString([]byte(fixture.Suggestion)) + "\t" + base64.StdEncoding.EncodeToString([]byte(token))
	undoRestore := "1\tedit-in-buffer\tsafe\t\t\t\t" + base64.StdEncoding.EncodeToString([]byte(fixture.Input))
	checker := filepath.Join(directory, "close-enough")
	checkerScript := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *\"--operation pre-send\"*) printf '%s\\n' \"$REWRITE\" ;; *\"--operation undo\"*) case \"$UNDO_OUTCOME\" in restore) printf '%s\\n' \"$UNDO_RESTORE\" ;; expired) printf '1\\tnone\\t\\t\\t\\t\\t\\n' ;; malformed) printf 'malformed\\n' ;; unavailable) exit 1 ;; esac ;; *) exit 1 ;; esac\n"
	if err := os.WriteFile(checker, []byte(checkerScript), 0o700); err != nil {
		t.Fatal(err)
	}
	capture, result := filepath.Join(directory, "calls"), filepath.Join(directory, "result")
	environment := append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "CAPTURE="+capture, "REWRITE="+rewrite, "UNDO_RESTORE="+undoRestore, "UNDO_OUTCOME="+fixture.UndoOutcome, "SUBMIT_AFTER_UNDO="+strconv.FormatBool(fixture.SubmitAfterUndo), "RESULT="+result)
	var command *exec.Cmd
	switch shellName {
	case "zsh":
		harness := `typeset -g BIND_G=list-expand
zle() { :; }
bindkey() {
  if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then
    print '"^M" accept-line'
  elif [[ "$1" == -M && "$2" == main && "$3" == '^G' && "$#" == 3 ]]; then
    print "\"^G\" $BIND_G"
  elif [[ "$1" == -M && "$2" == main && "$3" == '^G' && "$#" == 4 ]]; then
    BIND_G="$4"
  fi
}
autoload() { :; }
add-zsh-hook() { :; }
source "$1"
BUFFER="$2"
_close_enough_check; first=$?
rewritten="$BUFFER"
_close_enough_undo_rewrite
after="$BUFFER"
second=skip
if [[ "$SUBMIT_AFTER_UNDO" == true ]]; then
  _close_enough_check; second=$?
fi
print -rn -- "$first|$rewritten|$after|$second|$BIND_G|$_CLOSE_ENOUGH_UNDO_WIDGET" > "$RESULT"`
		command = exec.Command(shellPath, "-fc", harness, "zsh", adapter, fixture.Input)
	case "bash":
		harness := `BIND_G=abort
bind() {
  if [ "$1" = -p ]; then
    printf '"\\C-m": accept-line\n"\\C-g": %s\n' "$BIND_G"
    return
  fi
  if [ "$1" = -X ]; then
    [ "$BIND_G" = _close_enough_undo_rewrite ] && printf '"\\C-g" "_close_enough_undo_rewrite"\n'
    return
  fi
  if [ "$1" = -x ]; then
    case "$2" in
      *C-g*) BIND_G=_close_enough_undo_rewrite ;;
    esac
    return
  fi
  BIND_G="${1##*: }"
}
source "$1"
_close_enough_submit_line() { :; }
READLINE_LINE="$2"
_close_enough_accept_line; first=$?
rewritten="$READLINE_LINE"
_close_enough_undo_rewrite
after="$READLINE_LINE"
second=skip
if [ "$SUBMIT_AFTER_UNDO" = true ]; then
  _close_enough_accept_line; second=$?
fi
printf '%s|%s|%s|%s|%s|%s' "$first" "$rewritten" "$after" "$second" "$BIND_G" "$_close_enough_undo_binding" > "$RESULT"`
		command = exec.Command(shellPath, "--noprofile", "--norc", "-c", harness, "bash", adapter, fixture.Input)
	case "fish":
		harness := `set -g EXECUTES 0
set -g BIND_G unbound
function bind
  if test (count $argv) -eq 1
    if test "$argv[1]" = \r
      echo "bind --preset enter execute"
      return 0
    end
    if test "$argv[1]" = \cg; and test "$BIND_G" != unbound
      echo "bind \\cg $BIND_G"
      return 0
    end
    return 1
  end
  if test "$argv[1]" = --erase
    set -g BIND_G unbound
    return 0
  end
  if test "$argv[1]" = \cg
    set -g BIND_G "$argv[2]"
  end
end
function commandline
  if test "$argv[1]" = -b
    printf '%s' "$BUFFER"
  else if test "$argv[1]" = -r
    set -g BUFFER "$argv[2]"
  else if test "$argv[1]" = -f; and test "$argv[2]" = execute
    set -g EXECUTES (math $EXECUTES + 1)
  end
end
source "$argv[1]"
set -g BUFFER "$argv[2]"
_close_enough_accept_line
set -g REWRITTEN "$BUFFER"
_close_enough_undo_rewrite
if test "$SUBMIT_AFTER_UNDO" = true
  _close_enough_accept_line
end
printf '%s|%s|%s|%s' "$REWRITTEN" "$BUFFER" "$EXECUTES" "$BIND_G" > "$RESULT"`
		command = exec.Command(shellPath, "-c", harness, adapter, fixture.Input)
	default:
		t.Fatalf("unsupported shell %q", shellName)
	}
	command.Env = environment
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("%s harness: %v\n%s", shellName, err, output)
	}
	data, err := os.ReadFile(result)
	if err != nil {
		t.Fatal(err)
	}
	if shellName == "fish" {
		wantSubmits := "0"
		if fixture.SubmitAfterUndo {
			wantSubmits = "1"
		}
		if got, want := string(data), fixture.Suggestion+"|"+fixture.WantBuffer+"|"+wantSubmits+"|unbound"; got != want {
			t.Fatalf("undo flow = %q, want %q", got, want)
		}
	} else if shellName == "zsh" {
		wantSecondEnter := "skip"
		if fixture.SubmitAfterUndo {
			wantSecondEnter = "0"
		}
		if got, want := string(data), "1|"+fixture.Suggestion+"|"+fixture.WantBuffer+"|"+wantSecondEnter+"|list-expand|"; got != want {
			t.Fatalf("undo flow = %q, want %q", got, want)
		}
	} else {
		wantSecondEnter := "skip"
		if fixture.SubmitAfterUndo {
			wantSecondEnter = "0"
		}
		if got, want := string(data), "1|"+fixture.Suggestion+"|"+fixture.WantBuffer+"|"+wantSecondEnter+"|abort|"; got != want {
			t.Fatalf("undo flow = %q, want %q", got, want)
		}
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{"--format undo-record", "--operation undo", "--token " + token} {
		if !strings.Contains(string(calls), value) {
			t.Fatalf("daemon calls missing %q: %q", value, calls)
		}
	}
	if got := strings.Count(string(calls), "--operation"); got != 3 || strings.Count(string(calls), "--operation pre-send") != 1 || strings.Count(string(calls), "--operation undo") != 1 {
		t.Fatalf("daemon calls = %q", calls)
	}
}

func TestAdaptersExposePendingRewriteUndoBindings(t *testing.T) {
	tests := []struct {
		shell   string
		needles []string
	}{
		{"zsh", []string{"_CLOSE_ENOUGH_PENDING_UNDO_TOKEN", "_close_enough_undo_rewrite", "--operation undo --shell zsh", "press Ctrl-G to undo"}},
		{"fish", []string{"_CLOSE_ENOUGH_PENDING_UNDO_TOKEN", "_close_enough_undo_rewrite", "--operation undo --shell fish", "press Ctrl-G to undo"}},
		{"powershell", []string{"CloseEnoughPendingUndoToken", "Invoke-CloseEnoughPendingRewriteUndo", "--operation undo --shell powershell", "Ctrl+g", "press Ctrl-G to undo"}},
	}
	for _, test := range tests {
		t.Run(test.shell, func(t *testing.T) {
			script, err := Script(test.shell)
			if err != nil {
				t.Fatal(err)
			}
			for _, needle := range test.needles {
				if !strings.Contains(script, needle) {
					t.Fatalf("%s adapter missing undo behavior %q", test.shell, needle)
				}
			}
		})
	}
}

func TestAdaptersForwardBoundedPostFailureEvidence(t *testing.T) {
	for _, test := range []struct {
		name  string
		wants []string
	}{
		{"zsh", []string{`local failure_output="exit status $exit_status"`, `capture read --socket "$CLOSE_ENOUGH_CAPTURE_SOCKET"`, `--failure-output "$failure_output"`}},
		{"bash", []string{`failure_output="exit status $exit_status"`, `capture read --socket "$CLOSE_ENOUGH_CAPTURE_SOCKET"`, `--failure-output "$failure_output"`}},
		{"fish", []string{`--failure-output "exit status $command_status"`}},
		{"powershell", []string{`--failure-output $failureOutput`}},
	} {
		t.Run(test.name, func(t *testing.T) {
			script, err := Script(test.name)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(script, "--operation post-failure") {
				t.Fatalf("%s adapter does not forward bounded failure evidence", test.name)
			}
			for _, want := range test.wants {
				if !strings.Contains(script, want) {
					t.Fatalf("%s adapter missing failure evidence behavior %q", test.name, want)
				}
			}
		})
	}
}

func TestHighRiskConfirmationCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/high_risk_confirmation.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []highRiskConfirmationFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("high-risk confirmation corpus is empty")
	}
	for _, shellName := range []string{"zsh", "fish"} {
		shellPath, err := exec.LookPath(shellName)
		if err != nil {
			t.Run(shellName, func(t *testing.T) { t.Skip(shellName + " unavailable") })
			continue
		}
		for _, fixture := range fixtures {
			t.Run(shellName+"/"+fixture.Name, func(t *testing.T) {
				if fixture.Name == "" || fixture.Command == "" {
					t.Fatalf("invalid high-risk confirmation fixture: %#v", fixture)
				}
				runHighRiskConfirmationFixture(t, shellName, shellPath, fixture)
			})
		}
	}
}

func runHighRiskConfirmationFixture(t *testing.T, shellName, shellPath string, fixture highRiskConfirmationFixture) {
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
	checkerScript := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \" $* \" in *\" --operation handshake \"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *\" --operation pre-send \"*) if test -e \"$STATE\"; then printf '1\\tsubmit\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; else : > \"$STATE\"; printf '1\\tinterrupt\\thigh\\t1\\t\\t\\t%s\\n' \"$SUGGESTION\"; fi ;; *) exit 1 ;; esac\n"
	if err := os.WriteFile(checker, []byte(checkerScript), 0o700); err != nil {
		t.Fatal(err)
	}
	capture, state, result := filepath.Join(directory, "calls"), filepath.Join(directory, "state"), filepath.Join(directory, "result")
	environment := append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "CAPTURE="+capture, "STATE="+state, "SUGGESTION="+base64.StdEncoding.EncodeToString([]byte("press Enter again")), "RESULT="+result)
	var command *exec.Cmd
	switch shellName {
	case "zsh":
		harness := `zle() { :; }; bindkey() { if [[ "$1" == -M && "$2" == main && "$3" == '^M' && "$#" == 3 ]]; then print '"^M" accept-line'; fi; }; autoload() { :; }; add-zsh-hook() { :; }; source "$1"; BUFFER="$2"; _close_enough_check; first=$?; first_buffer="$BUFFER"; _close_enough_check; second=$?; print -rn -- "$first|$first_buffer|$second|$BUFFER" > "$RESULT"`
		command = exec.Command(shellPath, "-fc", harness, "zsh", adapter, fixture.Command)
	case "bash":
		harness := `source "$1"; _close_enough_submit_line() { :; }; READLINE_LINE="$2"; _close_enough_accept_line; first=$?; first_line="$READLINE_LINE"; _close_enough_accept_line; second=$?; printf '%s' "$first|$first_line|$second|$READLINE_LINE" > "$RESULT"`
		command = exec.Command(shellPath, "--noprofile", "--norc", "-c", harness, "bash", adapter, fixture.Command)
	case "fish":
		harness := `set -g EXECUTES 0; function bind; if test (count $argv) -eq 1; echo "bind --preset enter execute"; end; end; function commandline; if test "$argv[1]" = -b; printf '%s' "$BUFFER"; else if test "$argv[1]" = -f; and test "$argv[2]" = execute; set -g EXECUTES (math $EXECUTES + 1); end; end; source "$argv[1]"; set -g BUFFER "$argv[2]"; _close_enough_accept_line; set -g FIRST_BUFFER "$BUFFER"; _close_enough_accept_line; printf '%s' "$FIRST_BUFFER|$BUFFER|$EXECUTES" > "$RESULT"`
		command = exec.Command(shellPath, "-c", harness, adapter, fixture.Command)
	default:
		t.Fatalf("unsupported shell %q", shellName)
	}
	command.Env = environment
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("%s harness: %v\n%s", shellName, err, output)
	}
	data, err := os.ReadFile(result)
	if err != nil {
		t.Fatal(err)
	}
	if shellName == "fish" {
		if got, want := string(data), fixture.Command+"|"+fixture.Command+"|1"; got != want {
			t.Fatalf("confirmation flow = %q, want %q", got, want)
		}
	} else if got, want := string(data), "1|"+fixture.Command+"|0|"+fixture.Command; got != want {
		t.Fatalf("confirmation flow = %q, want %q", got, want)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "--operation"); got != 3 || strings.Count(string(calls), "--operation pre-send") != 2 || strings.Count(string(calls), fixture.Command) != 2 {
		t.Fatalf("daemon calls = %q", calls)
	}
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
	repaint := strings.Index(branch, "commandline -f repaint")
	execute := strings.Index(branch[repaint:], "commandline -f execute")
	if repaint < 0 || execute < 0 || !strings.Contains(branch[:repaint], "echo \"close-enough") || !strings.Contains(branch[repaint:repaint+execute], "return") {
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
	check := `--operation pre-send --shell zsh --session "$$" --ensure=false --format undo-record --command "$command"`
	if !strings.Contains(script, capture) || strings.Index(script, check) < strings.Index(script, capture) || strings.Contains(script, `--command "$BUFFER"`) {
		t.Fatalf("zsh pre-execution check does not use a captured buffer: %q", script)
	}
	if !strings.Contains(script, `2>/dev/null)" || { _CLOSE_ENOUGH_DAEMON_READY=0; return 0; }`) {
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '1\\tinterrupt\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n' ;; esac\n"), 0o700); err != nil {
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '1\\thint\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n' ;; esac\n"), 0o700); err != nil {
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

func TestZshInteractivePTYDaemonFailureSubmitsCommand(t *testing.T) {
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
	capture := filepath.Join(directory, "calls")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\nexit 1\n"), 0o700); err != nil {
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
expect "CE> "
send -- "exit\r"
expect eof`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker, "CAPTURE="+capture)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("zsh PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("daemon failure did not submit buffered command: %v\n%s", err, output)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(calls), "--operation handshake") {
		t.Fatalf("adapter did not invoke the daemon handshake: %q", calls)
	}
}

/*
The Bash adapter was removed because its bind-x implementation evaluated a
buffer inside a shell function and replaced the user's DEBUG trap. The tests
below document the retired adapter and are intentionally excluded until a
semantics-preserving Bash integration exists.

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
	check := `--operation pre-send --shell bash --session "$$" --ensure=false --format undo-record --command "$command"`
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

func TestBashInterruptPreservesBufferBeforeReturning(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	interrupt := `if [ "$action" = interrupt ]; then`
	start := strings.Index(script, interrupt)
	if start < 0 {
		t.Fatalf("bash interrupt branch is missing: %q", script)
	}
	branch := script[start:]
	if strings.Contains(branch, "READLINE_LINE=") || !strings.Contains(branch, "_close_enough_pending_confirmation=\"$command\"\n    return 1") {
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
	trigger := `daemon request --operation post-failure --shell bash --session "$$" --token "$token" --format record --command "$command"`
	if !strings.Contains(script, "_close_enough_debug() {") || !strings.Contains(script, "_close_enough_last_command=$BASH_COMMAND") || !strings.Contains(branch, `local status=$? command="$_close_enough_last_command"`) || !strings.Contains(branch, consume) || !strings.Contains(branch, trigger) || strings.Contains(branch, "close-enough check --stage post") || strings.Index(branch, consume) > strings.Index(branch, trigger) {
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
	if !strings.Contains(checkBody, `_close_enough_handshake || { _close_enough_submit_line "$command"; return; }`) || !strings.Contains(checkBody, `--operation pre-send --shell bash --session "$$" --ensure=false --format undo-record`) || !strings.Contains(checkBody, "_close_enough_daemon_ready=0;") || !strings.Contains(checkBody, `_close_enough_pending_confirmation=''; _close_enough_submit_line "$command"; return`) {
		t.Fatalf("bash handshake fallback = %q", checkBody)
	}
}

func TestBashProtocolDecodingPreservesEmptyFields(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `if base64 --decode </dev/null >/dev/null 2>&1; then`) || !strings.Contains(script, `printf %s "$1" | base64 --decode`) || !strings.Contains(script, `separator=$'\034'`) || !strings.Contains(script, `record="${record//$'\t'/$separator}"`) || !strings.Contains(script, `IFS="$separator" read -r -a fields <<< "$record"`) || !strings.Contains(script, `[ "${#fields[@]}" -eq 7 ] || [ "${#fields[@]}" -eq 8 ] || { _close_enough_submit_line "$command"; return; }`) || !strings.Contains(script, `suggestion="$(_close_enough_decode "$suggestion")" || { _close_enough_submit_line "$command"; return; }`) {
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
		harness := `source "$1"; _close_enough_submit_line() { :; }; READLINE_LINE="$2"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$RESULT"`
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
			harness := `source "$1"; _close_enough_submit_line() { :; }; READLINE_LINE="$2"; _close_enough_accept_line; printf %s "$READLINE_LINE" > "$RESULT"`
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
	harness := `source "$1"; _close_enough_submit_line() { :; }; READLINE_LINE=gti; _close_enough_accept_line; first=$?; first_line="$READLINE_LINE"; _close_enough_accept_line; second=$?; printf '%s|%s|%s|%s\n' "$first" "$first_line" "$second" "$READLINE_LINE"`
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
	harness := `source "$1"; _close_enough_submit_line() { :; }; READLINE_LINE='git push --force'; _close_enough_accept_line; first=$?; first_line="$READLINE_LINE"; _close_enough_accept_line; second=$?; printf '%s|%s|%s|%s\n' "$first" "$first_line" "$second" "$READLINE_LINE"`
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

*/

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
	check := `daemon request --operation pre-send --shell fish --session "$fish_pid" --ensure=false --format undo-record --command "$command"`
	if !strings.Contains(script, capture) || strings.Index(script, check) < strings.Index(script, capture) || strings.Contains(script, "--command (commandline -b)") {
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
	if start < 0 || !strings.Contains(script[start:], "set -l command_status $status") || !strings.Contains(script[start:], "set -l command $argv[1]") || !strings.Contains(script[start:], `if test -z "$command"`) || !strings.Contains(script[start:], `if test $command_status -ne 0`) || !strings.Contains(script[start:], `daemon request --operation post-failure --shell fish --session "$fish_pid" --token "$token" --format record --command "$command"`) || strings.Contains(script[start:], "close-enough check --stage post") {
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
	if !strings.Contains(checkBody, "_close_enough_handshake; or begin\n    commandline -f execute") || !strings.Contains(checkBody, `--operation pre-send --shell fish --session "$fish_pid" --ensure=false --format undo-record`) || !strings.Contains(checkBody, "set -g _CLOSE_ENOUGH_DAEMON_READY 0") {
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

func TestFishRestoresPreexistingEnterBinding(t *testing.T) {
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
	capture := filepath.Join(directory, "bindings")
	harness := `set -g CURRENT 'bind --preset enter execute'; function bind; if test (count $argv) -eq 1; echo $CURRENT; else if test "$argv[1]" = --erase; set -g CURRENT 'bind --preset enter execute'; echo erase >> "$CAPTURE"; else set -g CURRENT "bind $argv[1] $argv[2]"; echo $argv[2] >> "$CAPTURE"; end; end; source "$argv[1]"; _close_enough_restore_enter; echo $CURRENT`
	command := exec.Command(fish, "-c", harness, adapter)
	command.Env = append(os.Environ(), "CAPTURE="+capture)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("fish harness: %v\n%s", err, output)
	}
	if got := string(output); got != "bind --preset enter execute\n" {
		t.Fatalf("restored binding = %q", got)
	}
	bindings, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(bindings); got != "_close_enough_accept_line\nerase\n" {
		t.Fatalf("binding changes = %q", got)
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '1\\tinterrupt\\tsafe\\t1\\tY2hlY2s=\\t\\ta2VlcCBidWZmZXI=\\n' ;; esac\n"), 0o700); err != nil {
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
expect_text {close-enough [safe/1]: keep buffer (check)}
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ntouch "+strconv.Quote(checked)+"\ncase \"$*\" in *\"--operation handshake\"*) printf '1\\tready\\t\\t\\t\\t\\t\\n' ;; *) printf '1\\thint\\tsafe\\t1\\t\\t\\ta2VlcCBidWZmZXI=\\n' ;; esac\n"), 0o700); err != nil {
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

func TestFishInteractivePTYDaemonFailureSubmitsCommand(t *testing.T) {
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
	capture := filepath.Join(directory, "calls")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\nexit 1\n"), 0o700); err != nil {
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
spawn -noecho env TERM=dumb fish --no-config
expect {
  -re {> } {}
  timeout { puts stderr "timed out waiting for initial prompt"; exit 1 }
}
send -- "function fish_prompt; echo -n 'CE> '; end\r"
expect_text "function fish_prompt; echo -n 'CE> '; end\r\n"
expect_text {CE> }
send -- "source \$ADAPTER\r"
expect_text "source \$ADAPTER\r\n"
expect_text {CE> }
send -- "touch \$MARKER\r"
expect_text "touch \$MARKER\r\n"
expect_text {CE> }
send -- "exit\r"
expect {
  eof {}
  timeout { puts stderr "timed out waiting for EOF"; exit 1 }
}`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker, "CAPTURE="+capture)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("fish PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("daemon failure did not submit buffered command: %v\n%s", err, output)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(calls), "--operation handshake") {
		t.Fatalf("adapter did not invoke the daemon handshake: %q", calls)
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
	check := "--operation pre-send --shell powershell --session $PID --ensure=false --command $command"
	if !strings.Contains(script, capture) || strings.Index(script, check) < strings.Index(script, capture) || strings.Contains(script, "--command $line") {
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
	if !strings.Contains(script, "function global:prompt {") || !strings.Contains(script, "$status = $?") || !strings.Contains(script, "$entry = Get-History -Count 1") || !strings.Contains(script, "$entry.Id -ne $global:CloseEnoughLastHistoryId") || !strings.Contains(script, `daemon request --operation post-failure --shell powershell --session $PID --token $token --format json --command $entry.CommandLine`) || strings.Contains(script, "close-enough check --stage post") {
		t.Fatalf("PowerShell post-failure hook is missing or unsafe: %q", script)
	}
}

func TestPowerShellUsesDaemonForPreAndPostDecisions(t *testing.T) {
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
	if !strings.Contains(script, "daemon request --operation pre-send --shell powershell") || !strings.Contains(script, "daemon request --operation post-failure --shell powershell") {
		t.Fatalf("PowerShell script does not delegate both stages to the daemon: %q", script)
	}
}

func TestPowerShellHandshakeFailsOpen(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	handshake := "function global:Test-CloseEnoughDaemonHandshake {"
	handshakeStart := strings.Index(script, handshake)
	if handshakeStart < 0 {
		t.Fatalf("PowerShell handshake is missing: %q", script)
	}
	handshakeEnd := strings.Index(script[handshakeStart:], "function global:Allow-CloseEnoughDiagnostic")
	if handshakeEnd < 0 {
		t.Fatalf("PowerShell handshake function is unterminated: %q", script)
	}
	handshakeBody := script[handshakeStart : handshakeStart+handshakeEnd]
	if !strings.Contains(handshakeBody, `daemon request --operation handshake --shell powershell --session $PID --ensure=true --format json`) || !strings.Contains(handshakeBody, `$decision.version -ne 1 -or $decision.action -ne 'ready'`) || !strings.Contains(handshakeBody, "$global:CloseEnoughDaemonReady = $true") {
		t.Fatalf("PowerShell handshake contract = %q", handshakeBody)
	}
	handlerStart := strings.Index(script, "Set-PSReadLineKeyHandler -Key Enter -ScriptBlock {")
	handlerEnd := strings.Index(script[handlerStart:], "function global:Test-CloseEnoughDaemonHandshake")
	if handlerStart < 0 || handlerEnd < 0 {
		t.Fatalf("PowerShell Enter handler is missing: %q", script)
	}
	handler := script[handlerStart : handlerStart+handlerEnd]
	if !strings.Contains(handler, "if (-not (Test-CloseEnoughDaemonHandshake)) { [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine(); return }") || !strings.Contains(handler, `--operation pre-send --shell powershell --session $PID --ensure=false`) || strings.Count(handler, "[Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine(); return") < 4 {
		t.Fatalf("PowerShell handshake fallback = %q", handler)
	}
}

func TestPowerShellProtocolDecodingFailsOpenOnMalformedJSON(t *testing.T) {
	script, err := Script("pwsh")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `$record = & close-enough daemon request --operation pre-send --shell powershell --session $PID --ensure=false --command $command`) || !strings.Contains(script, `$LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($record)`) || !strings.Contains(script, `ConvertFrom-Json -ErrorAction Stop`) || !strings.Contains(script, `catch { $global:CloseEnoughDaemonReady = $false;`) {
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ncase \"$*\" in *\"--operation handshake\"*) printf '{\"version\":1,\"action\":\"ready\"}\\n' ;; *) printf '{\"version\":1,\"action\":\"interrupt\",\"risk\":\"safe\",\"confidence\":1,\"suggestion\":\"keep buffer\"}\\n' ;; esac\n"), 0o700); err != nil {
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ntouch "+strconv.Quote(checked)+"\ncase \"$*\" in *\"--operation handshake\"*) printf '{\"version\":1,\"action\":\"ready\"}\\n' ;; *) printf '{\"version\":1,\"action\":\"hint\",\"risk\":\"safe\",\"confidence\":1,\"suggestion\":\"keep buffer\"}\\n' ;; esac\n"), 0o700); err != nil {
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

func TestPowerShellInteractivePTYSafeRewriteSubmitsOnSecondEnter(t *testing.T) {
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
	capture := filepath.Join(directory, "calls")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '{\"version\":1,\"action\":\"ready\"}\\n' ;; *\"--command gti\"*) printf '{\"version\":1,\"action\":\"rewrite\",\"risk\":\"safe\",\"confidence\":1,\"suggestion\":\"Set-Content -NoNewline -Path $env:MARKER -Value executed\",\"explanation\":\"fixed\"}\\n' ;; *) printf '{\"version\":1,\"action\":\"submit\"}\\n' ;; esac\n"), 0o700); err != nil {
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
send -- "gti\r"
expect_text {close-enough corrected: Set-Content -NoNewline -Path $env:MARKER -Value executed (fixed; press Enter again)}
send -- "\r"
expect_regex {PS .*?> }
send -- "exit\r"
expect {
  eof {}
  timeout { puts stderr "timed out waiting for EOF"; exit 1 }
}`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "CAPTURE="+capture, "MARKER="+marker)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("PowerShell PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("safe rewrite did not submit on second Enter: %v\n%s", err, output)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "--operation pre-send"); got != 2 {
		t.Fatalf("pre-send requests = %d, want 2: %q", got, calls)
	}
}

func TestPowerShellInteractivePTYHighRiskConfirmationSubmitsOnSecondEnter(t *testing.T) {
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
	capture := filepath.Join(directory, "calls")
	state := filepath.Join(directory, "state")
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\ncase \"$*\" in *\"--operation handshake\"*) printf '{\"version\":1,\"action\":\"ready\"}\\n' ;; *\"--command Set-Content\"*) if test -e \"$STATE\"; then printf '{\"version\":1,\"action\":\"submit\"}\\n'; else : > \"$STATE\"; printf '{\"version\":1,\"action\":\"interrupt\",\"risk\":\"high\",\"confidence\":1,\"suggestion\":\"press Enter again\",\"explanation\":\"confirmation required\"}\\n'; fi ;; *) printf '{\"version\":1,\"action\":\"submit\"}\\n' ;; esac\n"), 0o700); err != nil {
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
expect_text {close-enough [high/1]: press Enter again (confirmation required)}
send -- "\r"
expect_regex {PS .*?> }
send -- "exit\r"
expect {
  eof {}
  timeout { puts stderr "timed out waiting for EOF"; exit 1 }
}`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "CAPTURE="+capture, "MARKER="+marker, "STATE="+state)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("PowerShell PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("high-risk confirmation did not submit on second Enter: %v\n%s", err, output)
	}
	calls, err := os.ReadFile(capture)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(string(calls), "--operation pre-send"); got != 3 {
		t.Fatalf("pre-send requests = %d, want 3: %q", got, calls)
	}
}

func TestPowerShellInteractivePTYRestoresDefaultEnterBinding(t *testing.T) {
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\ncase \"$*\" in *\"--operation handshake\"*) printf '{\"version\":1,\"action\":\"ready\"}\\n' ;; *) printf '{\"version\":1,\"action\":\"none\"}\\n' ;; esac\n"), 0o700); err != nil {
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
send -- "Restore-CloseEnoughEnterHandler; (Get-PSReadLineKeyHandler -Chord Enter).Function\r"
expect_text {AcceptLine}
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

func TestPowerShellInteractivePTYPreservesCustomEnterBinding(t *testing.T) {
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
expect_regex {PS.*>}
send -- "Set-PSReadLineKeyHandler -Key Enter -ScriptBlock { Write-Host CE_CUSTOM_ENTER; \[Microsoft.PowerShell.PSConsoleReadLine\]::AcceptLine() }\r"
expect_text {CE_CUSTOM_ENTER}
expect_regex {PS.*>}
send -- ". \$env:ADAPTER; Write-Output (\[Text.Encoding\]::UTF8.GetString(\[Convert\]::FromBase64String('Q0VfQURBUFRFUl9SRUFEWQ==')))\r"
expect_text {CE_CUSTOM_ENTER}
expect_text {CE_ADAPTER_READY}
expect_regex {PS.*>}
send -- "Restore-CloseEnoughEnterHandler; Write-Output CE_CUSTOM_RESTORED\r"
expect_text {CE_CUSTOM_ENTER}
expect_text {CE_CUSTOM_RESTORED}
expect_regex {PS.*>}
send -- "exit\r"
expect_text {CE_CUSTOM_ENTER}
expect {
  eof {}
  timeout { puts stderr "timed out waiting for EOF"; exit 1 }
}`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "ADAPTER="+adapter)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("PowerShell PTY: %v\n%s", err, output)
	}
}

func TestPowerShellInteractivePTYDaemonFailureSubmitsCommand(t *testing.T) {
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nexit 1\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(directory, "executed")
	pty := `set timeout 5
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
send -- ". \$env:ADAPTER\r"
expect_regex {PS .*?> }
send -- "Set-Content -NoNewline -Path \$env:MARKER -Value executed\r"
expect_regex {PS .*?> }
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
		t.Fatalf("daemon failure did not submit buffered command: %v\n%s", err, output)
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
	preexec := "function _close_enough_preexec {"
	precmd := "function _close_enough_precmd {"
	preexecStart, precmdStart := strings.Index(script, preexec), strings.Index(script, precmd)
	if preexecStart < 0 || precmdStart < preexecStart || !strings.Contains(script[preexecStart:precmdStart], `_CLOSE_ENOUGH_LAST_COMMAND="$1"`) || !strings.Contains(script[preexecStart:precmdStart], "_CLOSE_ENOUGH_PENDING_REWRITE=''") {
		t.Fatalf("zsh post-failure hooks are missing: %q", script)
	}
	end := strings.Index(script[precmdStart:], "autoload -Uz add-zsh-hook")
	if end < 0 {
		t.Fatalf("zsh precmd hook is unterminated: %q", script)
	}
	branch := script[precmdStart : precmdStart+end]
	consume := "_CLOSE_ENOUGH_LAST_COMMAND=''"
	trigger := `daemon request --operation post-failure --shell zsh --session "$$" --token "$token" --format record --command "$command"`
	if !strings.Contains(branch, `local exit_status=$? command="$_CLOSE_ENOUGH_LAST_COMMAND"`) || !strings.Contains(branch, consume) || !strings.Contains(branch, `[[ -z "$command" ]] && return`) || !strings.Contains(branch, trigger) || strings.Contains(branch, "close-enough check --stage post") || strings.Index(branch, consume) > strings.Index(branch, trigger) {
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
	if !strings.Contains(checkBody, "_close_enough_handshake || return 0") || !strings.Contains(checkBody, `--operation pre-send --shell zsh --session "$$" --ensure=false --format undo-record`) || !strings.Contains(checkBody, "_CLOSE_ENOUGH_DAEMON_READY=0; return 0") {
		t.Fatalf("zsh handshake fallback = %q", checkBody)
	}
}

func TestZshProtocolDecodingFailsOpenOnMalformedRecords(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `if base64 --decode </dev/null >/dev/null 2>&1; then`) || !strings.Contains(script, `print -rn -- "$1" | base64 --decode`) || strings.Contains(script, "_close_enough_decode { echo") || !strings.Contains(script, `fields=("${(@ps:\t:)record}")`) || !strings.Contains(script, `(( ${#fields} == 7 || ${#fields} == 8 )) || return 0`) || !strings.Contains(script, `suggestion="$(_close_enough_decode "$suggestion")" || return 0`) {
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
	for _, name := range []string{"csh"} {
		if _, err := Script(name); err == nil {
			t.Fatalf("unsupported script %q succeeded", name)
		}
		if _, err := ContractFor(name); err == nil {
			t.Fatalf("unsupported contract %q succeeded", name)
		}
		if got := Doctor("/bin/"+name, "test"); got.Supported || !slices.Equal(got.Limitations, []string{"unsupported shell"}) || !slices.Equal(got.RemediationHints, []string{"use bash, zsh, fish, or powershell"}) {
			t.Fatalf("unsupported doctor result for %q: %#v", name, got)
		}
	}
}

func TestExperimentalCaptureBootstrapIsRestrictedToBashAndZsh(t *testing.T) {
	for _, name := range []string{"bash", "zsh"} {
		bootstrap, err := ExperimentalCaptureBootstrap(name)
		if err != nil || !strings.Contains(bootstrap, "exec close-enough capture start --shell "+name) || !strings.Contains(bootstrap, "CLOSE_ENOUGH_CAPTURE_ACTIVE") {
			t.Fatalf("bootstrap(%q) = %q, %v", name, bootstrap, err)
		}
	}
	if _, err := ExperimentalCaptureBootstrap("fish"); err == nil {
		t.Fatal("accepted experimental capture for fish")
	}
}

func TestBashAdapterPreservesPromptAndDebugTrapWithoutPreSendHook(t *testing.T) {
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
	checkerScript := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALLS\"\nprintf '1\\thint\\thigh\\thigh\\tY2F1c2U=\\t\\tZ2l0IHN0YXR1cw==\\n'\n"
	if err := os.WriteFile(checker, []byte(checkerScript), 0o700); err != nil {
		t.Fatal(err)
	}
	calls, trapState := filepath.Join(directory, "calls"), filepath.Join(directory, "trap")
	harness := `set -o history
PROMPT_COMMAND='printf existing'
trap ':' DEBUG
source "$1"
history -s 'git sttaus'
false
_close_enough_bash_precmd
printf '%s' "$PROMPT_COMMAND" > "$PROMPT_STATE"
trap -p DEBUG > "$TRAP_STATE"`
	command := exec.Command(bash, "--noprofile", "--norc", "-c", harness, "bash", adapter)
	command.Env = append(os.Environ(), "PATH="+directory+string(os.PathListSeparator)+os.Getenv("PATH"), "CALLS="+calls, "PROMPT_STATE="+filepath.Join(directory, "prompt"), "TRAP_STATE="+trapState)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("bash adapter harness: %v: %s", err, output)
	}
	prompt, err := os.ReadFile(filepath.Join(directory, "prompt"))
	if err != nil || !strings.HasPrefix(string(prompt), "printf existing;") || !strings.Contains(string(prompt), "_close_enough_bash_precmd") {
		t.Fatalf("PROMPT_COMMAND = %q, %v", prompt, err)
	}
	trapOutput, err := os.ReadFile(trapState)
	if err != nil || !strings.Contains(string(trapOutput), "DEBUG") {
		t.Fatalf("DEBUG trap = %q, %v", trapOutput, err)
	}
	data, err := os.ReadFile(calls)
	if err != nil || !strings.Contains(string(data), "--operation post-failure --shell bash") || strings.Contains(string(data), "pre-send") {
		t.Fatalf("daemon calls = %q, %v", data, err)
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
