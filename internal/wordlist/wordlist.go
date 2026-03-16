package wordlist

import (
	"bufio"
	"io/fs"
	"math/rand/v2"
	"strings"
)

var wordsFS fs.FS

func Init(f fs.FS) { wordsFS = f }

type WordList struct {
	Name  string
	Words []string
}

func Load(name string) (*WordList, error) {
	path := "assets/words/" + name + ".txt"
	f, err := wordsFS.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var words []string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		w := strings.TrimSpace(sc.Text())
		if w != "" {
			words = append(words, w)
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	return &WordList{Name: name, Words: words}, nil
}

func (wl *WordList) Pick(n int) []string {
	out := make([]string, n)
	for i := range out {
		out[i] = wl.Words[rand.IntN(len(wl.Words))]
	}
	return out
}

func Available() []string {
	if wordsFS == nil {
		return nil
	}
	entries, err := fs.ReadDir(wordsFS, "assets/words")
	if err != nil {
		return nil
	}
	var names []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if strings.HasSuffix(name, ".txt") {
			names = append(names, strings.TrimSuffix(name, ".txt"))
		}
	}
	return names
}
