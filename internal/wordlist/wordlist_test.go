package wordlist

import (
	"testing"
	"testing/fstest"
)

func testFS() fstest.MapFS {
	return fstest.MapFS{
		"assets/words/english_200.txt": &fstest.MapFile{
			Data: []byte("the\nquick\nbrown\nfox\njumps\nover\nlazy\ndog\n"),
		},
		"assets/words/code_keywords.txt": &fstest.MapFile{
			Data: []byte("func\nvar\nreturn\nif\nelse\n"),
		},
	}
}

func TestLoad(t *testing.T) {
	Init(testFS())
	wl, err := Load("english_200")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(wl.Words) != 8 {
		t.Errorf("expected 8 words, got %d", len(wl.Words))
	}
	if wl.Name != "english_200" {
		t.Errorf("expected name english_200, got %s", wl.Name)
	}
}

func TestLoadNotFound(t *testing.T) {
	Init(testFS())
	_, err := Load("nonexistent")
	if err == nil {
		t.Error("expected error for nonexistent wordlist")
	}
}

func TestPick(t *testing.T) {
	Init(testFS())
	wl, _ := Load("english_200")
	picked := wl.Pick(5)
	if len(picked) != 5 {
		t.Errorf("expected 5 words, got %d", len(picked))
	}
	for _, w := range picked {
		if w == "" {
			t.Error("empty word in Pick output")
		}
	}
}

func TestAvailable(t *testing.T) {
	Init(testFS())
	names := Available()
	if len(names) != 2 {
		t.Errorf("expected 2 available lists, got %d", len(names))
	}
	found := map[string]bool{}
	for _, n := range names {
		found[n] = true
	}
	if !found["english_200"] || !found["code_keywords"] {
		t.Errorf("missing expected wordlists: %v", names)
	}
}

func TestLoadEmptyLines(t *testing.T) {
	fs := fstest.MapFS{
		"assets/words/sparse.txt": &fstest.MapFile{
			Data: []byte("hello\n\n  \nworld\n"),
		},
	}
	Init(fs)
	wl, err := Load("sparse")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(wl.Words) != 2 {
		t.Errorf("expected 2 words (empty lines skipped), got %d", len(wl.Words))
	}
}
