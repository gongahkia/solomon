package packs

import (
	"errors"
	"strings"
)

type RuntimeMatch struct {
	PackID     string
	RuleID     string
	Suggestion string
	Cause      string
	Risk       string
	Rationale  string
}

type RuntimeResolver struct {
	packs []CompiledPack
}

func NewBundledRuntimeResolver() (RuntimeResolver, error) {
	loaded, err := LoadBundled()
	if err != nil {
		return RuntimeResolver{}, err
	}
	return NewRuntimeResolver(loaded)
}

func NewRuntimeResolver(loaded []Pack) (RuntimeResolver, error) {
	resolved, err := Resolve(loaded)
	if err != nil {
		return RuntimeResolver{}, err
	}
	return RuntimeResolver{packs: resolved}, nil
}

func (r RuntimeResolver) MatchLine(line string) (RuntimeMatch, bool) {
	if !simpleCommandLine(line) {
		return RuntimeMatch{}, false
	}
	words := strings.Fields(line)
	if len(words) < 2 {
		return RuntimeMatch{}, false
	}
	command := words[0]
	value := strings.Join(words[1:], " ")
	for _, pack := range r.packs {
		rule, ok := pack.Match(command, value)
		if !ok {
			continue
		}
		return RuntimeMatch{PackID: pack.Pack.ID, RuleID: rule.ID, Suggestion: command + " " + rule.Replacement, Cause: rule.Cause, Risk: string(rule.Risk), Rationale: rule.RiskRationale}, true
	}
	return RuntimeMatch{}, false
}

func simpleCommandLine(line string) bool {
	if strings.TrimSpace(line) == "" || strings.TrimSpace(line) != line {
		return false
	}
	if len(line) > 8<<10 {
		return false
	}
	if strings.ContainsAny(line, "'\"\\`$;|&()\r\n") {
		return false
	}
	return !strings.ContainsRune(line, 0)
}

func (r RuntimeResolver) Validate() error {
	if len(r.packs) == 0 {
		return errors.New("runtime resolver has no packs")
	}
	return nil
}
