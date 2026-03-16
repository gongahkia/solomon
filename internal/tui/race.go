package tui

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/gongahkia/monke/internal/engine"
	"github.com/gongahkia/monke/internal/multiplayer"
)

type startRaceMsg struct {
	client *multiplayer.Client
	words  []string
}

type RaceModel struct {
	engine   *engine.Engine
	client   *multiplayer.Client
	players  map[string]multiplayer.ProgressPayload
	rankings []multiplayer.PlayerResult
	finished bool
	width    int
	height   int
}

type raceTickMsg time.Time

func doRaceTick() tea.Cmd {
	return tea.Tick(200*time.Millisecond, func(t time.Time) tea.Msg { return raceTickMsg(t) })
}

func newRace(client *multiplayer.Client, words []string) (RaceModel, tea.Cmd) {
	e := engine.New(words, "time", 0)
	m := RaceModel{
		engine:  e,
		client:  client,
		players: make(map[string]multiplayer.ProgressPayload),
		width:   80, height: 24,
	}
	return m, tea.Batch(doRaceTick(), listenServer(client))
}

func (m RaceModel) Update(msg tea.Msg) (RaceModel, tea.Cmd) {
	switch msg := msg.(type) {
	case raceTickMsg:
		if m.finished {
			return m, nil
		}
		// send progress
		if m.client != nil && m.engine.Started() {
			_ = m.client.Send(multiplayer.MsgProgress, multiplayer.ProgressPayload{
				CharsTyped: m.engine.CharsTyped(),
				TotalChars: m.engine.TotalChars(),
				WPM:        m.engine.CurrentWPM(),
				Finished:   m.engine.Finished,
			})
		}
		return m, doRaceTick()
	case serverMsg:
		sm := multiplayer.Message(msg)
		switch sm.Type {
		case multiplayer.MsgProgress:
			prog, _ := multiplayer.DecodePayload[multiplayer.ProgressPayload](sm)
			m.players[prog.Name] = prog
		case multiplayer.MsgResult:
			result, _ := multiplayer.DecodePayload[multiplayer.ResultPayload](sm)
			m.rankings = result.Rankings
			m.finished = true
		}
		if m.client != nil {
			return m, listenServer(m.client)
		}
		return m, nil
	case tea.KeyMsg:
		if m.finished {
			switch msg.String() {
			case "enter", "esc":
				if m.client != nil {
					m.client.Close()
				}
				return m, func() tea.Msg { return switchStateMsg{state: stateMenu} }
			case "ctrl+c":
				return m, tea.Quit
			}
			return m, nil
		}
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc":
			if m.client != nil {
				m.engine.Finish()
				_ = m.client.Send(multiplayer.MsgFinish, nil)
				m.client.Close()
			}
			return m, func() tea.Msg { return switchStateMsg{state: stateMenu} }
		case "backspace":
			m.engine.Backspace()
		case "ctrl+w":
			m.engine.BackspaceWord()
		case " ":
			if m.engine.CharIdx > 0 {
				m.engine.NextWord()
			}
		default:
			if len(msg.String()) == 1 && msg.String()[0] >= 32 && msg.String()[0] <= 126 {
				m.engine.TypeChar(rune(msg.String()[0]))
			}
		}
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
	}
	return m, nil
}

func (m RaceModel) View() string {
	var b strings.Builder
	b.WriteString(th.title.Render("RACE") + "\n\n")
	if m.finished && len(m.rankings) > 0 {
		b.WriteString(th.subtitle.Render("  results") + "\n\n")
		for _, r := range m.rankings {
			medal := "  "
			if r.Place == 1 {
				medal = th.accent.Render("1.")
			} else {
				medal = th.dim.Render(fmt.Sprintf("%d.", r.Place))
			}
			b.WriteString(fmt.Sprintf("  %s %s  %s\n",
				medal,
				th.bold.Render(fmt.Sprintf("%-15s", r.Name)),
				th.wpm.Render(fmt.Sprintf("%.0f wpm", r.WPM)),
			))
		}
		b.WriteString("\n" + th.hint.Render("enter/esc: menu"))
		return b.String()
	}
	// player progress bars
	for name, prog := range m.players {
		pct := 0
		if prog.TotalChars > 0 {
			pct = prog.CharsTyped * 100 / prog.TotalChars
		}
		bar := progressBar(pct, 100, 30)
		b.WriteString(fmt.Sprintf("  %s %s %s\n",
			th.bold.Render(fmt.Sprintf("%-12s", name)),
			bar,
			th.dim.Render(fmt.Sprintf("%.0f wpm", prog.WPM)),
		))
	}
	b.WriteString("\n")
	// own typing area (simplified - show current + next word)
	if m.engine.WordIdx < len(m.engine.Words) {
		w := m.engine.Words[m.engine.WordIdx]
		var wordStr strings.Builder
		for ci, c := range w.Chars {
			isCursor := ci == m.engine.CharIdx
			switch {
			case isCursor:
				wordStr.WriteString(th.cursor.Render(string(c.Expected)))
			case c.Status == engine.Correct:
				wordStr.WriteString(th.correct.Render(string(c.Expected)))
			case c.Status == engine.Incorrect:
				wordStr.WriteString(th.incorrect.Render(string(c.Typed)))
			default:
				wordStr.WriteString(th.upcoming.Render(string(c.Expected)))
			}
		}
		for _, c := range w.Extra {
			wordStr.WriteString(th.extra.Render(string(c.Typed)))
		}
		b.WriteString("  " + wordStr.String())
		if m.engine.WordIdx+1 < len(m.engine.Words) {
			next := m.engine.Words[m.engine.WordIdx+1]
			var nextStr strings.Builder
			for _, c := range next.Chars {
				nextStr.WriteRune(c.Expected)
			}
			b.WriteString("  " + th.upcoming.Render(nextStr.String()))
		}
	}
	b.WriteString("\n\n")
	b.WriteString(statLine(m.engine.CurrentWPM(), m.engine.CurrentAccuracy(), ""))
	return b.String()
}
