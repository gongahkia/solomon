package packs

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
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

// LoadInstalled loads only canonical regular pack files from a managed directory.
// Its result is sorted and resolved before it is returned so callers cannot depend
// on directory iteration order or accept ambiguous pack matchers.
func LoadInstalled(directory string) ([]Pack, error) {
	info, err := os.Lstat(directory)
	if errors.Is(err, os.ErrNotExist) {
		return []Pack{}, nil
	}
	if err != nil {
		return nil, err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("installed pack directory is not a real directory")
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, err
	}
	result := make([]Pack, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return nil, fmt.Errorf("installed pack %q is a symbolic link", entry.Name())
		}
		entryInfo, err := entry.Info()
		if err != nil {
			return nil, err
		}
		if !entryInfo.Mode().IsRegular() {
			return nil, fmt.Errorf("installed pack %q is not a regular file", entry.Name())
		}
		pack, err := Load(filepath.Join(directory, entry.Name()))
		if err != nil {
			return nil, fmt.Errorf("installed pack %q: %w", entry.Name(), err)
		}
		if entry.Name() != installedPackName(pack) {
			return nil, fmt.Errorf("installed pack %q does not have its canonical name", entry.Name())
		}
		if _, err := Compile(pack); err != nil {
			return nil, fmt.Errorf("installed pack %q: %w", entry.Name(), err)
		}
		result = append(result, pack)
	}
	sort.Slice(result, func(left, right int) bool {
		if result[left].ID == result[right].ID {
			return result[left].Version < result[right].Version
		}
		return result[left].ID < result[right].ID
	})
	if _, err := Resolve(result); err != nil {
		return nil, err
	}
	return result, nil
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
