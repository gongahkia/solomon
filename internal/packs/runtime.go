package packs

import (
	"context"
	"errors"
	"strings"

	"github.com/gongahkia/close-enough/internal/diagnose"
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
	match, ok, _ := r.MatchLineContext(context.Background(), line)
	return match, ok
}

func (r RuntimeResolver) MatchLineContext(ctx context.Context, line string) (RuntimeMatch, bool, error) {
	if err := ctx.Err(); err != nil {
		return RuntimeMatch{}, false, err
	}
	if !simpleCommandLine(line) {
		return RuntimeMatch{}, false, nil
	}
	match, ok, err := r.MatchWordsContext(ctx, strings.Fields(line))
	if err != nil {
		return RuntimeMatch{}, false, err
	}
	if !ok {
		return RuntimeMatch{}, false, nil
	}
	return RuntimeMatch{PackID: match.PackID, RuleID: match.RuleID, Suggestion: match.Suggestion, Cause: match.Cause, Risk: string(match.Risk), Rationale: match.Rationale}, true, nil
}

func (r RuntimeResolver) MatchWords(words []string) (diagnose.SemanticMatch, bool) {
	match, ok, _ := r.MatchWordsContext(context.Background(), words)
	return match, ok
}

func (r RuntimeResolver) MatchWordsContext(ctx context.Context, words []string) (diagnose.SemanticMatch, bool, error) {
	if err := ctx.Err(); err != nil {
		return diagnose.SemanticMatch{}, false, err
	}
	if len(words) < 2 {
		return diagnose.SemanticMatch{}, false, nil
	}
	command := words[0]
	value := strings.Join(words[1:], " ")
	for _, pack := range r.packs {
		if err := ctx.Err(); err != nil {
			return diagnose.SemanticMatch{}, false, err
		}
		rule, ok, err := pack.MatchContext(ctx, command, value)
		if err != nil {
			return diagnose.SemanticMatch{}, false, err
		}
		if ok {
			return runtimeSemanticMatch(pack, rule, words, nil), true, nil
		}
		rule, ok, err = pack.MatchContext(ctx, command, words[1])
		if err != nil {
			return diagnose.SemanticMatch{}, false, err
		}
		if ok {
			return runtimeSemanticMatch(pack, rule, words, words[2:]), true, nil
		}
	}
	return diagnose.SemanticMatch{}, false, nil
}

func runtimeSemanticMatch(pack CompiledPack, rule Rule, words, suffix []string) diagnose.SemanticMatch {
	replacement := rule.Replacement
	if len(suffix) > 0 {
		replacement += " " + strings.Join(suffix, " ")
	}
	match := diagnose.SemanticMatch{PackID: pack.Pack.ID, RuleID: rule.ID, Suggestion: words[0] + " " + replacement, Cause: rule.Cause, Risk: rule.Risk, Rationale: rule.RiskRationale}
	if len(words) >= 2 && !strings.ContainsRune(rule.Replacement, ' ') {
		match.Original, match.Replacement, match.Occurrence = words[1], rule.Replacement, 1
	}
	return match
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
