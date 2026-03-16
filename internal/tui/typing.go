package tui

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/gongahkia/monke/internal/engine"
	"github.com/gongahkia/monke/internal/wordlist"
)

type typingConfig struct {
	Mode     string // "time" or "words"
	Param    int    // seconds or word count
	WordList string
}

type TypingModel struct {
	engine   *engine.Engine
	config   typingConfig
	deadline time.Time
	width    int
	height   int
}

type tickMsg time.Time

func doTick() tea.Cmd {
	return tea.Tick(500*time.Millisecond, func(t time.Time) tea.Msg { return tickMsg(t) })
}

type snapshotMsg time.Time

func doSnapshot() tea.Cmd {
	return tea.Tick(time.Second, func(t time.Time) tea.Msg { return snapshotMsg(t) })
}

func newTyping(cfg typingConfig) (TypingModel, tea.Cmd) {
	numWords := 200 // generate enough words
	if cfg.Mode == "words" {
		numWords = cfg.Param + 10
	}
	wl, err := wordlist.Load(cfg.WordList)
	if err != nil {
		wl = &wordlist.WordList{Name: "fallback", Words: []string{"the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog"}}
	}
	words := wl.Pick(numWords)
	e := engine.New(words, cfg.Mode, cfg.Param)
	m := TypingModel{engine: e, config: cfg, width: 80, height: 24}
	return m, tea.Batch(doTick(), doSnapshot())
}

func (m TypingModel) Update(msg tea.Msg) (TypingModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tickMsg:
		if m.engine.Finished {
			return m, nil
		}
		if m.config.Mode == "time" && m.engine.Started() {
			if m.deadline.IsZero() {
				m.deadline = time.Now().Add(time.Duration(m.config.Param) * time.Second)
			}
			if time.Now().After(m.deadline) {
				result := m.engine.Finish()
				return m, func() tea.Msg { return showResultsMsg{result: result, config: m.config} }
			}
		}
		return m, doTick()
	case snapshotMsg:
		m.engine.RecordSnapshot()
		if m.engine.Finished {
			return m, nil
		}
		return m, doSnapshot()
	case tea.KeyMsg:
		if m.engine.Finished {
			return m, nil
		}
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc":
			return m, func() tea.Msg { return switchStateMsg{state: stateMenu} }
		case "tab":
			nm, cmd := newTyping(m.config)
			nm.width = m.width
			nm.height = m.height
			return nm, cmd
		case "backspace":
			m.engine.Backspace()
		case "ctrl+w", "alt+backspace":
			m.engine.BackspaceWord()
		case " ":
			if m.engine.CharIdx > 0 || len(m.engine.Words[m.engine.WordIdx].Extra) > 0 {
				m.engine.NextWord()
				if m.config.Mode == "words" && m.engine.Finished {
					result := m.engine.Finish()
					return m, func() tea.Msg { return showResultsMsg{result: result, config: m.config} }
				}
			}
		default:
			if len(msg.String()) == 1 && msg.String()[0] >= 32 && msg.String()[0] <= 126 {
				if m.config.Mode == "time" && !m.engine.Started() {
					m.deadline = time.Now().Add(time.Duration(m.config.Param) * time.Second)
				}
				m.engine.TypeChar(rune(msg.String()[0]))
			}
		}
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
	}
	return m, nil
}

func (m TypingModel) View() string {
	var b strings.Builder
	// stat line
	var extra string
	if m.config.Mode == "time" {
		remaining := 0
		if !m.deadline.IsZero() {
			remaining = int(time.Until(m.deadline).Seconds())
			if remaining < 0 {
				remaining = 0
			}
		} else {
			remaining = m.config.Param
		}
		extra = fmt.Sprintf("%ds", remaining)
	} else {
		extra = fmt.Sprintf("%d/%d", m.engine.WordIdx, m.config.Param)
	}
	b.WriteString(statLine(m.engine.CurrentWPM(), m.engine.CurrentAccuracy(), extra))
	b.WriteString("\n\n")
	// render words
	maxWidth := m.width - 4
	if maxWidth < 40 {
		maxWidth = 40
	}
	lineWidth := 0
	var lines []string
	var currentLine strings.Builder
	scrollStart := 0 // which line the current word is on
	currentWordLine := 0
	lineCount := 0
	for wi, w := range m.engine.Words {
		wordLen := len(w.Chars) + len(w.Extra) + 1 // +1 for space
		if lineWidth+wordLen > maxWidth && lineWidth > 0 {
			lines = append(lines, currentLine.String())
			currentLine.Reset()
			lineWidth = 0
			lineCount++
		}
		if wi == m.engine.WordIdx {
			currentWordLine = lineCount
		}
		if lineWidth > 0 {
			currentLine.WriteString(" ")
			lineWidth++
		}
		for ci, c := range w.Chars {
			isCursor := wi == m.engine.WordIdx && ci == m.engine.CharIdx
			var s string
			switch {
			case isCursor:
				s = th.cursor.Render(string(c.Expected))
			case c.Status == engine.Correct:
				s = th.correct.Render(string(c.Expected))
			case c.Status == engine.Incorrect:
				s = th.incorrect.Render(string(c.Typed))
			case c.Status == engine.Missed:
				s = th.dim.Render(string(c.Expected))
			default: // upcoming
				s = th.upcoming.Render(string(c.Expected))
			}
			currentLine.WriteString(s)
		}
		for _, c := range w.Extra {
			s := th.extra.Render(string(c.Typed))
			currentLine.WriteString(s)
		}
		// cursor at end of word (in extra zone)
		if wi == m.engine.WordIdx && m.engine.CharIdx >= len(w.Chars) {
			currentLine.WriteString(th.cursor.Render(" "))
		}
		lineWidth += len(w.Chars) + len(w.Extra)
	}
	if currentLine.Len() > 0 {
		lines = append(lines, currentLine.String())
	}
	// show ~3 lines around current word
	scrollStart = currentWordLine - 1
	if scrollStart < 0 {
		scrollStart = 0
	}
	visibleLines := 3
	end := scrollStart + visibleLines
	if end > len(lines) {
		end = len(lines)
	}
	for i := scrollStart; i < end; i++ {
		b.WriteString(lines[i])
		b.WriteString("\n")
	}
	b.WriteString("\n")
	b.WriteString(th.hint.Render("tab: restart  │  esc: menu  │  ctrl+w: delete word"))
	return b.String()
}
