package engine

import (
	"testing"
)

func TestTypeCharCorrect(t *testing.T) {
	e := New([]string{"hello"}, "words", 1)
	for _, c := range "hello" {
		e.TypeChar(c)
	}
	for _, c := range e.Words[0].Chars {
		if c.Status != Correct {
			t.Errorf("expected Correct, got %d for char %c", c.Status, c.Expected)
		}
	}
}

func TestTypeCharIncorrect(t *testing.T) {
	e := New([]string{"hello"}, "words", 1)
	e.TypeChar('x')
	if e.Words[0].Chars[0].Status != Incorrect {
		t.Error("expected Incorrect")
	}
}

func TestExtraChars(t *testing.T) {
	e := New([]string{"hi"}, "words", 1)
	e.TypeChar('h')
	e.TypeChar('i')
	e.TypeChar('x') // extra
	if len(e.Words[0].Extra) != 1 {
		t.Errorf("expected 1 extra, got %d", len(e.Words[0].Extra))
	}
}

func TestBackspace(t *testing.T) {
	e := New([]string{"ab"}, "words", 1)
	e.TypeChar('a')
	e.TypeChar('x')
	e.Backspace()
	if e.CharIdx != 1 {
		t.Errorf("expected CharIdx=1, got %d", e.CharIdx)
	}
	if e.Words[0].Chars[1].Status != Upcoming {
		t.Error("expected Upcoming after backspace")
	}
}

func TestBackspaceExtra(t *testing.T) {
	e := New([]string{"ab"}, "words", 1)
	e.TypeChar('a')
	e.TypeChar('b')
	e.TypeChar('x') // extra
	e.Backspace()
	if len(e.Words[0].Extra) != 0 {
		t.Error("extra should be cleared")
	}
}

func TestBackspaceWord(t *testing.T) {
	e := New([]string{"hello"}, "words", 1)
	e.TypeChar('h')
	e.TypeChar('e')
	e.TypeChar('l')
	e.BackspaceWord()
	if e.CharIdx != 0 {
		t.Error("CharIdx should be 0")
	}
	for _, c := range e.Words[0].Chars {
		if c.Status != Upcoming {
			t.Error("all chars should be Upcoming")
		}
	}
}

func TestNextWord(t *testing.T) {
	e := New([]string{"ab", "cd"}, "words", 2)
	e.TypeChar('a') // type only first char
	e.NextWord()
	if e.WordIdx != 1 {
		t.Error("should advance to word 1")
	}
	if e.Words[0].Chars[1].Status != Missed {
		t.Error("untyped char should be Missed")
	}
}

func TestFinishWordsMode(t *testing.T) {
	e := New([]string{"a", "b"}, "words", 2)
	e.TypeChar('a')
	e.NextWord()
	e.TypeChar('b')
	e.NextWord() // should trigger finish
	if !e.Finished {
		t.Error("should be finished")
	}
}

func TestAccuracy(t *testing.T) {
	e := New([]string{"ab"}, "words", 1)
	e.TypeChar('a') // correct
	e.TypeChar('x') // incorrect
	acc := e.CurrentAccuracy()
	if acc < 49.0 || acc > 51.0 {
		t.Errorf("expected ~50%% accuracy, got %.1f", acc)
	}
}

func TestCharsTypedAndTotal(t *testing.T) {
	e := New([]string{"hello", "world"}, "words", 2)
	if e.TotalChars() != 10 {
		t.Errorf("expected 10 total chars, got %d", e.TotalChars())
	}
	e.TypeChar('h')
	e.TypeChar('e')
	if e.CharsTyped() != 2 {
		t.Errorf("expected 2 chars typed, got %d", e.CharsTyped())
	}
}
