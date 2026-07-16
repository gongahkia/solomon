package shell

import "fmt"

type DoctorResult struct {
	Shell       string   `json:"shell"`
	OS          string   `json:"os"`
	Supported   bool     `json:"supported"`
	Tier        string   `json:"tier,omitempty"`
	Features    []string `json:"features,omitempty"`
	Limitations []string `json:"limitations,omitempty"`
}

func Script(name string) (string, error) {
	switch name {
	case "zsh":
		return zshScript, nil
	case "bash":
		return bashScript, nil
	case "fish":
		return fishScript, nil
	case "powershell", "pwsh":
		return powerShellScript, nil
	default:
		return "", fmt.Errorf("unsupported shell %q", name)
	}
}

func Doctor(shellPath, osName string) DoctorResult {
	name := shellName(shellPath)
	result := DoctorResult{Shell: name, OS: osName}
	switch name {
	case "zsh", "bash":
		result.Supported, result.Tier, result.Features = true, "first-class", []string{"pre-execution", "post-failure", "hint", "interrupt", "rewrite"}
	case "fish":
		result.Supported, result.Tier, result.Features, result.Limitations = true, "tiered", []string{"command-not-found", "custom enter binding"}, []string{"adapter replaces enter binding"}
	case "pwsh", "powershell":
		result.Supported, result.Tier, result.Features, result.Limitations = true, "tiered", []string{"command validation", "post-failure"}, []string{"requires PSReadLine"}
	default:
		result.Limitations = []string{"unsupported shell"}
	}
	return result
}

func shellName(value string) string {
	for i := len(value) - 1; i >= 0; i-- {
		if value[i] == '/' || value[i] == '\\' {
			return value[i+1:]
		}
	}
	return value
}
