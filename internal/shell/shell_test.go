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
