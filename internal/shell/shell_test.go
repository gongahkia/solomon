package shell

import (
	"encoding/base64"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\nprintf '%s\\n' \"$RECORD\"\n"), 0o700); err != nil {
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
expect "close-enough [safe/1]: keep buffer"
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

func TestBashInterruptClearsBufferBeforeReturning(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	interrupt := `if [ "$action" = interrupt ]; then`
	start := strings.Index(script, interrupt)
	if start < 0 || !strings.Contains(script[start:], "READLINE_LINE=''\n    return 1") {
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
	trigger := `--stage post --format plain --command "$command"`
	if !strings.Contains(script, "_close_enough_debug() { _close_enough_last_command=$BASH_COMMAND; }") || !strings.Contains(branch, `local status=$? command="$_close_enough_last_command"`) || !strings.Contains(branch, consume) || !strings.Contains(branch, trigger) || strings.Index(branch, consume) > strings.Index(branch, trigger) {
		t.Fatalf("bash post-failure hook does not consume command safely: %q", branch)
	}
}

func TestBashPropagatesModeAndDisplayConfiguration(t *testing.T) {
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
	if !strings.Contains(script, "--stage pre --format record") || !strings.Contains(script, "--stage post --format plain") {
		t.Fatalf("bash script does not delegate mode and display configuration: %q", script)
	}
}

func TestBashProtocolDecodingPreservesEmptyFields(t *testing.T) {
	script, err := Script("bash")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `separator=$'\034'`) || !strings.Contains(script, `record="${record//$'\t'/$separator}"`) || !strings.Contains(script, `IFS="$separator" read -r -a fields <<< "$record"`) || !strings.Contains(script, `[ "${#fields[@]}" -eq 7 ] || return`) || !strings.Contains(script, `suggestion="$(_close_enough_decode "$suggestion")" || return`) {
		t.Fatalf("bash protocol decoder is not binary-safe and fixed-field: %q", script)
	}
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\nprintf '%s\\n' \"$RECORD\"\n"), 0o700); err != nil {
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
expect "close-enough [safe/1]: keep buffer"
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
	if start < 0 || !strings.Contains(script[start:], "set -l status $status") || !strings.Contains(script[start:], "set -l command $argv[1]") || !strings.Contains(script[start:], `test $status -ne 0; and test -n "$command"`) || !strings.Contains(script[start:], `--stage post --format plain --command "$command"`) {
		t.Fatalf("fish post-failure hook is missing or unsafe: %q", script)
	}
}

func TestFishPropagatesModeAndDisplayConfiguration(t *testing.T) {
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
	if !strings.Contains(script, "--stage pre --format record") || !strings.Contains(script, "--stage post --format plain") {
		t.Fatalf("fish script does not delegate mode and display configuration: %q", script)
	}
}

func TestFishProtocolDecodingValidatesFixedFields(t *testing.T) {
	script, err := Script("fish")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(script, `function _close_enough_decode`) || !strings.Contains(script, `printf '%s' "$argv[1]" | base64`) || !strings.Contains(script, "if test (count $fields) -ne 7") || !strings.Contains(script, `set -l suggestion (_close_enough_decode "$fields[7]")`) || !strings.Contains(script, "or return") {
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
	if err := os.WriteFile(checker, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\nprintf '%s\\n' \"$RECORD\"\n"), 0o700); err != nil {
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
spawn -noecho fish --no-config
expect -re {> }
send -- "function fish_prompt; echo -n 'CE> '; end\r"
expect "CE> "
send -- "source \$ADAPTER\r"
expect "CE> "
send -- "touch \$MARKER\r"
expect "close-enough [safe/1]: keep buffer"
send -- "\003"
expect "CE> "
send -- "test ! -e \$MARKER; and echo protected\r"
expect "protected"
expect "CE> "
send -- "exit\r"
expect eof`
	command := exec.Command(expect, "-c", pty)
	command.Env = append(os.Environ(), "PATH="+directory+":"+os.Getenv("PATH"), "ADAPTER="+adapter, "MARKER="+marker)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("fish PTY: %v\n%s", err, output)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("interrupt executed buffered command: %v", err)
	}
}

func TestPowerShellInitializationIsGuarded(t *testing.T) {
	script, err := Script("powershell")
	if err != nil {
		t.Fatal(err)
	}
	guard := "if (-not $global:CloseEnoughAdapterLoaded) {\n$global:CloseEnoughAdapterLoaded = $true"
	if !strings.HasPrefix(script, "# close-enough PowerShell integration\n"+guard) || !strings.HasSuffix(strings.TrimSpace(script), "}") || strings.Count(script, "Set-PSReadLineKeyHandler -Key Enter") != 1 {
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
	preexec := `function _close_enough_preexec { _CLOSE_ENOUGH_LAST_COMMAND="$1" }`
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
	trigger := `--stage post --format plain --command "$command"`
	if !strings.Contains(branch, `local status=$? command="$_CLOSE_ENOUGH_LAST_COMMAND"`) || !strings.Contains(branch, consume) || !strings.Contains(branch, `[[ $status -eq 0 || -z "$command" ]] && return`) || !strings.Contains(branch, trigger) || strings.Index(branch, consume) > strings.Index(branch, trigger) {
		t.Fatalf("zsh post-failure trigger does not consume command safely: %q", branch)
	}
}

func TestZshPropagatesModeAndDisplayConfiguration(t *testing.T) {
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
	if !strings.Contains(script, "--stage pre --format record") || !strings.Contains(script, "--stage post --format plain") {
		t.Fatalf("zsh script does not delegate mode and display configuration: %q", script)
	}
}

func TestZshProtocolDecodingFailsOpenOnMalformedRecords(t *testing.T) {
	script, err := Script("zsh")
	if err != nil {
		t.Fatal(err)
	}
	decoder := `function _close_enough_decode { print -rn -- "$1" | { base64 --decode 2>/dev/null || base64 -D; } }`
	if !strings.Contains(script, decoder) || strings.Contains(script, "_close_enough_decode { echo") || !strings.Contains(script, `fields=("${(@ps:\t:)record}")`) || !strings.Contains(script, `(( ${#fields} == 7 )) || return 0`) || !strings.Contains(script, `suggestion="$(_close_enough_decode "$suggestion")" || return 0`) {
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
	if got := Doctor("/bin/csh", "test"); got.Supported || !slices.Equal(got.Limitations, []string{"unsupported shell"}) {
		t.Fatalf("unsupported doctor result: %#v", got)
	}
}
