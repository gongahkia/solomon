package packs

import (
	"embed"
	"fmt"
	"sort"
)

//go:embed bundled/*.json
var bundledFiles embed.FS

func BundledNames() ([]string, error) {
	entries, err := bundledFiles.ReadDir("bundled")
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() {
			names = append(names, entry.Name())
		}
	}
	sort.Strings(names)
	return names, nil
}

func LoadBundled() ([]Pack, error) {
	names, err := BundledNames()
	if err != nil {
		return nil, err
	}
	packs := make([]Pack, 0, len(names))
	for _, name := range names {
		data, err := bundledFiles.ReadFile("bundled/" + name)
		if err != nil {
			return nil, err
		}
		pack, err := decodePack(data)
		if err != nil {
			return nil, fmt.Errorf("bundled pack %q: %w", name, err)
		}
		packs = append(packs, pack)
	}
	if _, err := Resolve(packs); err != nil {
		return nil, err
	}
	return packs, nil
}
