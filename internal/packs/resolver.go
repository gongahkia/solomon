package packs

import (
	"fmt"
	"sort"
)

func Resolve(packs []Pack) ([]CompiledPack, error) {
	ordered := append([]Pack(nil), packs...)
	sort.Slice(ordered, func(left, right int) bool { return ordered[left].ID < ordered[right].ID })
	resolved := make([]CompiledPack, 0, len(ordered))
	seenPacks := map[string]struct{}{}
	seenMatchers := map[string]string{}
	for _, pack := range ordered {
		if _, exists := seenPacks[pack.ID]; exists {
			return nil, fmt.Errorf("duplicate pack id %q", pack.ID)
		}
		compiled, err := Compile(pack)
		if err != nil {
			return nil, err
		}
		for _, rule := range compiled.Rules {
			signature := rule.Command + "\x00" + rule.Pattern
			if previous, exists := seenMatchers[signature]; exists {
				return nil, fmt.Errorf("matcher conflict between %s and %s/%s", previous, pack.ID, rule.ID)
			}
			seenMatchers[signature] = pack.ID + "/" + rule.ID
		}
		seenPacks[pack.ID] = struct{}{}
		resolved = append(resolved, compiled)
	}
	return resolved, nil
}
