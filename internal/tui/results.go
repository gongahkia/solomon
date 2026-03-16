package tui

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/gongahkia/monke/internal/engine"
)

type ResultsModel struct {
	result engine.Result
	config typingConfig
	isPB   bool
}

type showResultsMsg struct {
	result engine.Result
	config typingConfig
}

func newResults(result engine.Result, cfg typingConfig) ResultsModel {
	return ResultsModel{result: result, config: cfg}
}

func (m ResultsModel) Update(msg tea.Msg) (ResultsModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "tab":
			return m, func() tea.Msg { return startTypingMsg{config: m.config} }
		case "enter", "esc":
			return m, func() tea.Msg { return switchStateMsg{state: stateMenu} }
		case "ctrl+c":
			return m, tea.Quit
		}
	}
	return m, nil
}

func (m ResultsModel) View() string {
	var b strings.Builder
	r := m.result
	header := "results"
	if m.isPB {
		header = "results  NEW PB!"
	}
	b.WriteString(th.title.Render(header) + "\n\n")
	b.WriteString(th.wpm.Render(fmt.Sprintf("  wpm   %6.1f", r.NetWPM)) + "\n")
	b.WriteString(th.dim.Render(fmt.Sprintf("  raw   %6.1f", r.RawWPM)) + "\n")
	b.WriteString(th.accuracy.Render(fmt.Sprintf("  acc   %5.1f%%", r.Accuracy)) + "\n")
	b.WriteString(th.subtitle.Render(fmt.Sprintf("  cons  %5.1f%%", r.Consistency)) + "\n\n")
	b.WriteString(th.correct.Render(fmt.Sprintf("  correct    %d", r.Correct)))
	b.WriteString(th.incorrect.Render(fmt.Sprintf("  |  incorrect  %d", r.Incorrect)))
	b.WriteString(th.extra.Render(fmt.Sprintf("  |  extra  %d", r.ExtraCount)))
	b.WriteString(th.dim.Render(fmt.Sprintf("  |  missed  %d", r.Missed)))
	b.WriteString("\n\n")
	b.WriteString(th.dim.Render(fmt.Sprintf("  mode: %s %d  |  words: %d  |  time: %s",
		r.Mode, m.config.Param, r.WordCount, r.Duration.Round(time.Millisecond))))
	b.WriteString("\n\n")
	b.WriteString(th.hint.Render("tab: restart  |  enter/esc: menu"))
	return b.String()
}
