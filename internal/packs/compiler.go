package packs

import "regexp"

type CompiledRule struct {
	Rule
	pattern *regexp.Regexp
}

type CompiledPack struct {
	Pack  Pack
	Rules []CompiledRule
}

func Compile(pack Pack) (CompiledPack, error) {
	if err := pack.Validate(); err != nil {
		return CompiledPack{}, err
	}
	compiled := CompiledPack{Pack: pack, Rules: make([]CompiledRule, 0, len(pack.Rules))}
	for _, rule := range pack.Rules {
		pattern, err := regexp.Compile(rule.Pattern)
		if err != nil {
			return CompiledPack{}, err
		}
		compiled.Rules = append(compiled.Rules, CompiledRule{Rule: rule, pattern: pattern})
	}
	return compiled, nil
}

func (p CompiledPack) Match(command, value string) (Rule, bool) {
	for _, rule := range p.Rules {
		if rule.Command == command && rule.pattern.MatchString(value) {
			return rule.Rule, true
		}
	}
	return Rule{}, false
}
