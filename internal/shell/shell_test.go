package shell

import (
	"encoding/json"
	"os"
	"slices"
	"strings"
	"testing"
)

type compatibilityFixture struct {
	Name         string       `json:"name"`
	Shell        string       `json:"shell"`
	Tier         string       `json:"tier"`
	Capabilities []Capability `json:"capabilities"`
	Limitations  []string     `json:"limitations"`
	Markers      []string     `json:"markers"`
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
			if contract.Shell != fixture.Shell || contract.Tier != fixture.Tier || !slices.Equal(contract.Capabilities, fixture.Capabilities) || !slices.Equal(contract.Limitations, fixture.Limitations) {
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
			if !doctor.Supported || doctor.Tier != fixture.Tier || !slices.Equal(doctor.Features, capabilityStrings(fixture.Capabilities)) || !slices.Equal(doctor.Limitations, fixture.Limitations) {
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
	execute := strings.Index(script, "commandline -f execute")
	if interrupt < 0 || execute < 0 || interrupt > execute {
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
	accept := "zle .accept-line"
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
	if strings.Index(script, "zle .accept-line") < end || !strings.Contains(script[end:], "return 1") {
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
	if widgetEnd < 0 || !strings.Contains(script[widgetStart:widgetStart+widgetEnd], "if ! _close_enough_check; then\n    return 0\n  fi\n  zle .accept-line") {
		t.Fatalf("zsh enter widget executes without an explicit suppression gate: %q", script)
	}
}

func TestContractReturnsIndependentSlices(t *testing.T) {
	first, err := ContractFor("zsh")
	if err != nil {
		t.Fatal(err)
	}
	first.Capabilities[0] = "mutated"
	second, err := ContractFor("zsh")
	if err != nil {
		t.Fatal(err)
	}
	if second.Capabilities[0] != PreExecution {
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
