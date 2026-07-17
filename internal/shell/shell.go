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
	Shell         string   `json:"shell"`
	OS            string   `json:"os"`
	Supported     bool     `json:"supported"`
	Tier          string   `json:"tier,omitempty"`
	Features      []string `json:"features,omitempty"`
	Configuration []string `json:"configuration,omitempty"`
	Limitations   []string `json:"limitations,omitempty"`
}

func Script(name string) (string, error) {
	adapter, ok := adapterFor(name)
	if !ok {
		return "", fmt.Errorf("unsupported shell %q", name)
	}
	return adapter.script, nil
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
		return result
	}
	result.Supported, result.Tier = true, contract.Tier
	result.Features = capabilityStrings(contract.Capabilities)
	result.Configuration = configurationStrings(contract.Configuration)
	result.Limitations = append([]string(nil), contract.Limitations...)
	return result
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
	"bash":           {Contract: Contract{Shell: "bash", Tier: "first-class", Capabilities: []Capability{PreExecution, PostFailure, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration, DisplayConfiguration}}, script: bashScript},
	"fish":           {Contract: Contract{Shell: "fish", Tier: "tiered", Capabilities: []Capability{PreExecution, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration}, Limitations: []string{"adapter replaces enter binding", "no post-failure diagnostics"}}, script: fishScript},
	"powershell":     {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration}, Limitations: []string{"requires PSReadLine", "no post-failure diagnostics"}}, script: powerShellScript},
	"powershell.exe": {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration}, Limitations: []string{"requires PSReadLine", "no post-failure diagnostics"}}, script: powerShellScript},
	"pwsh":           {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration}, Limitations: []string{"requires PSReadLine", "no post-failure diagnostics"}}, script: powerShellScript},
	"pwsh.exe":       {Contract: Contract{Shell: "powershell", Tier: "tiered", Capabilities: []Capability{PreExecution, Hint, Interrupt, Rewrite}, Configuration: []Configuration{ModeConfiguration}, Limitations: []string{"requires PSReadLine", "no post-failure diagnostics"}}, script: powerShellScript},
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
