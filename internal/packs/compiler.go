package packs

import (
	"context"
	"regexp"
)

type CompiledRule struct {
	Rule
	pattern *regexp.Regexp
}

type CompiledPack struct {
	Pack  Pack
	Rules []CompiledRule
}

func Compile(pack Pack) (CompiledPack, error) {
	if err := pack.CheckCompatibility(EngineVersion); err != nil {
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
	rule, ok, _ := p.MatchContext(context.Background(), command, value)
	return rule, ok
}

func (p CompiledPack) MatchContext(ctx context.Context, command, value string) (Rule, bool, error) {
	for _, rule := range p.Rules {
		if err := ctx.Err(); err != nil {
			return Rule{}, false, err
		}
		if rule.Command == command && rule.pattern.MatchString(value) {
			if err := ctx.Err(); err != nil {
				return Rule{}, false, err
			}
			return rule.Rule, true, nil
		}
	}
	return Rule{}, false, nil
}
