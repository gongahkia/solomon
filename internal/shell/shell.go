package shell

import (
	"fmt"
	"strings"
)

type Capability string

const (
	PreExecution Capability = "pre-execution"
	PostFailure  Capability = "post-failure"
	Hint         Capability = "hint"
	Interrupt    Capability = "interrupt"
	Rewrite      Capability = "rewrite"
)

type Configuration string

const (
	ModeConfiguration    Configuration = "mode"
	DisplayConfiguration Configuration = "display"
)

type Contract struct {
	Shell         string          `json:"shell"`
	Tier          string          `json:"tier"`
	Capabilities  []Capability    `json:"capabilities"`
	Configuration []Configuration `json:"configuration"`
	Limitations   []string        `json:"limitations,omitempty"`
}

type DoctorResult struct {
	Shell            string   `json:"shell"`
	OS               string   `json:"os"`
	Supported        bool     `json:"supported"`
	Tier             string   `json:"tier,omitempty"`
	Features         []string `json:"features,omitempty"`
	Configuration    []string `json:"configuration,omitempty"`
	Limitations      []string `json:"limitations,omitempty"`
	RemediationHints []string `json:"remediation_hints,omitempty"`
}

func Script(name string) (string, error) {
	adapter, ok := adapterFor(name)
	if !ok {
		return "", fmt.Errorf("unsupported shell %q", name)
	}
	return adapter.script, nil
}

func ExperimentalCaptureBootstrap(name string) (string, error) {
	switch shellName(name) {
	case "bash", "zsh":
		return `# solomon experimental output capture (opt-in)
if [[ -z "${SOLOMON_CAPTURE_ACTIVE:-}" ]]; then
  export SOLOMON_CAPTURE_ACTIVE=bootstrap
  exec solomon capture start --shell ` + shellName(name) + `
fi`, nil
	default:
		return "", fmt.Errorf("experimental output capture is available only for bash and zsh")
	}
}

func ContractFor(name string) (Contract, error) {
	adapter, ok := adapterFor(name)
	if !ok {
		return Contract{}, fmt.Errorf("unsupported shell %q", name)
	}
	return adapter.contract(), nil
}

func Doctor(shellPath, osName string) DoctorResult {
	name := shellName(shellPath)
	result := DoctorResult{Shell: name, OS: osName}
	contract, err := ContractFor(name)
	if err != nil {
		result.Limitations = []string{"unsupported shell"}
		result.RemediationHints = []string{"use bash, zsh, fish, or powershell"}
		return result
	}
	result.Supported, result.Tier = true, contract.Tier
	result.Features = capabilityStrings(contract.Capabilities)
	result.Configuration = configurationStrings(contract.Configuration)
	result.Limitations = append([]string(nil), contract.Limitations...)
	result.RemediationHints = remediationHints(contract.Limitations)
	return result
}

func remediationHints(limitations []string) []string {
	hints := make([]string, 0, len(limitations))
	for _, limitation := range limitations {
		switch limitation {
		case "adapter replaces enter binding":
			hints = append(hints, "review custom Enter bindings before initializing the adapter")
		case "requires PSReadLine":
			hints = append(hints, "install or enable PSReadLine, then initialize the adapter again")
		default:
			hints = append(hints, "review adapter limitation: "+limitation)
		}
	}
	return hints
}

func shellName(value string) string {
	for i := len(value) - 1; i >= 0; i-- {
		if value[i] == '/' || value[i] == '\\' {
			return value[i+1:]
		}
	}
	return strings.ToLower(strings.TrimSpace(value))
}

type adapter struct {
	Contract
	script string
}

func (a adapter) contract() Contract {
	return Contract{
		Shell:         a.Shell,
		Tier:          a.Tier,
		Capabilities:  append([]Capability(nil), a.Capabilities...),
		Configuration: append([]Configuration(nil), a.Configuration...),
		Limitations:   append([]string(nil), a.Limitations...),
	}
}

var adapters = map[string]adapter{
	"zsh":            {Contract: Contract{Shell: "zsh", Tier: "first-class", Capabilities: []Capability{PreExecution, PostFailure, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}}, script: zshScript},
	"bash":           {Contract: Contract{Shell: "bash", Tier: "tiered", Capabilities: []Capability{PostFailure, Hint}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}, Limitations: []string{"post-failure hints only", "no pre-execution interrupt or rewrite", "experimental output capture requires init flag and script utility"}}, script: bashScript},
	"fish":           {Contract: Contract{Shell: "fish", Tier: "tiered", Capabilities: []Capability{PreExecution, PostFailure, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}, Limitations: []string{"adapter replaces enter binding"}}, script: fishScript},
	"powershell":     {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, PostFailure, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}, Limitations: []string{"requires PSReadLine"}}, script: powerShellScript},
	"powershell.exe": {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, PostFailure, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}, Limitations: []string{"requires PSReadLine"}}, script: powerShellScript},
	"pwsh":           {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, PostFailure, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}, Limitations: []string{"requires PSReadLine"}}, script: powerShellScript},
	"pwsh.exe":       {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, PostFailure, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}, Limitations: []string{"requires PSReadLine"}}, script: powerShellScript},
}

func adapterFor(name string) (adapter, bool) {
	adapter, ok := adapters[shellName(name)]
	return adapter, ok
}

func capabilityStrings(capabilities []Capability) []string {
	result := make([]string, len(capabilities))
	for i, capability := range capabilities {
		result[i] = string(capability)
	}
	return result
}

func configurationStrings(configuration []Configuration) []string {
	result := make([]string, len(configuration))
	for i, setting := range configuration {
		result[i] = string(setting)
	}
	return result
}
