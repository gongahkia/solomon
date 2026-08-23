package packs

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

type RuntimeMatch struct {
	PackID     string
	RuleID     string
	Source     string
	Suggestion string
	Cause      string
	Risk       string
	Rationale  string
}

type RuntimeResolver struct {
	packs []runtimePack
}

type runtimePack struct {
	compiled CompiledPack
	source   string
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

// LoadInstalledVerified fails closed unless every managed pack still has a
// valid detached signature from a currently trusted publisher key.
func LoadInstalledVerified(directory string, keyring Keyring) ([]Pack, error) {
	loaded, err := LoadInstalled(directory)
	if err != nil {
		return nil, err
	}
	for _, pack := range loaded {
		target := filepath.Join(directory, installedPackName(pack))
		payload, err := readUserAuthorizedFile(target)
		if err != nil {
			return nil, err
		}
		signaturePath := target + ".sig"
		info, err := os.Lstat(signaturePath)
		if err != nil {
			return nil, fmt.Errorf("installed pack %q signature: %w", pack.ID, err)
		}
		if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
			return nil, fmt.Errorf("installed pack %q signature is not a regular file", pack.ID)
		}
		signature, err := readUserAuthorizedFile(signaturePath)
		if err != nil {
			return nil, err
		}
		if err := VerifyPublisherSignature(payload, signature, pack.Publisher, keyring); err != nil {
			return nil, fmt.Errorf("installed pack %q: %w", pack.ID, err)
		}
	}
	return loaded, nil
}

func NewRuntimeResolver(loaded []Pack) (RuntimeResolver, error) {
	return NewRuntimeResolverWithInstalled(loaded, nil)
}

// NewRuntimeResolverWithInstalled keeps embedded packs eligible for the
// configured rewrite policy while making every installed pack hint-only.
func NewRuntimeResolverWithInstalled(bundled, installed []Pack) (RuntimeResolver, error) {
	loaded := append(append([]Pack(nil), bundled...), installed...)
	resolved, err := Resolve(loaded)
	if err != nil {
		return RuntimeResolver{}, err
	}
	installedIDs := make(map[string]struct{}, len(installed))
	for _, pack := range installed {
		installedIDs[pack.ID] = struct{}{}
	}
	runtimePacks := make([]runtimePack, 0, len(resolved))
	for _, pack := range resolved {
		source := "bundled"
		if _, ok := installedIDs[pack.Pack.ID]; ok {
			source = "installed"
		}
		runtimePacks = append(runtimePacks, runtimePack{compiled: pack, source: source})
	}
	return RuntimeResolver{packs: runtimePacks}, nil
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
	return RuntimeMatch{PackID: match.PackID, RuleID: match.RuleID, Source: match.Source, Suggestion: match.Suggestion, Cause: match.Cause, Risk: string(match.Risk), Rationale: match.Rationale}, true, nil
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
	for _, runtimePack := range r.packs {
		if err := ctx.Err(); err != nil {
			return diagnose.SemanticMatch{}, false, err
		}
		for _, rule := range runtimePack.compiled.Rules {
			if err := ctx.Err(); err != nil {
				return diagnose.SemanticMatch{}, false, err
			}
			if rule.Command != command {
				continue
			}
			for argumentCount := len(words) - 1; argumentCount > 0; argumentCount-- {
				if argumentCount != len(words)-1 && !rule.PreserveTail {
					break
				}
				tail := words[argumentCount+1:]
				if len(tail) > 0 && !safeTail(tail) {
					continue
				}
				value := strings.Join(words[1:argumentCount+1], " ")
				indices := rule.pattern.FindStringSubmatchIndex(value)
				if indices == nil || indices[0] != 0 || indices[1] != len(value) {
					continue
				}
				return runtimeSemanticMatch(runtimePack, rule, words, value, indices, tail), true, nil
			}
		}
	}
	return diagnose.SemanticMatch{}, false, nil
}

func runtimeSemanticMatch(pack runtimePack, rule CompiledRule, words []string, value string, indices []int, tail []string) diagnose.SemanticMatch {
	replacement := string(rule.pattern.ExpandString(nil, rule.Replacement, value, indices))
	cause := string(rule.pattern.ExpandString(nil, rule.Cause, value, indices))
	if len(tail) > 0 {
		replacement += " " + strings.Join(tail, " ")
	}
	match := diagnose.SemanticMatch{PackID: pack.compiled.Pack.ID, RuleID: rule.ID, Source: pack.source, Suggestion: words[0] + " " + replacement, Cause: cause, Risk: rule.Risk, Rationale: rule.RiskRationale}
	if len(words) == 2 && len(tail) == 0 && !strings.ContainsRune(replacement, ' ') {
		match.Original, match.Replacement, match.Occurrence = words[1], replacement, 1
	}
	return match
}

func safeTail(words []string) bool {
	for _, word := range words {
		if word == "" || strings.ContainsAny(word, " \t\r\n'\"\\`$;|&()<>*?[]{}") {
			return false
		}
		for _, character := range word {
			if unicode.IsControl(character) || unicode.Is(unicode.Bidi_Control, character) {
				return false
			}
		}
	}
	return true
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
