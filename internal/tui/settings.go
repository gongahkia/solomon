package tui

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/gongahkia/monke/internal/config"
)

type applyThemeMsg struct{ name string }

type SettingsModel struct {
	cursor int
	cfg    *config.Config
	themes []string
	thIdx  int
}

func newSettings(cfg *config.Config) SettingsModel {
	themes := config.ThemeNames()
	thIdx := 0
	for i, t := range themes {
		if t == cfg.Theme {
			thIdx = i
			break
		}
	}
	return SettingsModel{cfg: cfg, themes: themes, thIdx: thIdx}
}

func (m SettingsModel) Update(msg tea.Msg) (SettingsModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j":
			// only theme setting for now, cursor stays at 0
		case "left", "h":
			if m.cursor == 0 && m.thIdx > 0 {
				m.thIdx--
				return m, func() tea.Msg { return applyThemeMsg{name: m.themes[m.thIdx]} }
			}
		case "right", "l":
			if m.cursor == 0 && m.thIdx < len(m.themes)-1 {
				m.thIdx++
				return m, func() tea.Msg { return applyThemeMsg{name: m.themes[m.thIdx]} }
			}
		case "esc":
			return m, func() tea.Msg { return switchStateMsg{state: stateMenu} }
		case "ctrl+c":
			return m, tea.Quit
		}
	}
	return m, nil
}

func (m SettingsModel) View() string {
	var b strings.Builder
	b.WriteString(th.title.Render("settings") + "\n\n")
	cursor := th.accent.Render("> ")
	b.WriteString(fmt.Sprintf("%s%s  %s  %s\n",
		cursor,
		th.bold.Render("theme"),
		th.dim.Render("<"),
		th.subtitle.Render(m.themes[m.thIdx]),
	))
	b.WriteString(th.dim.Render("                  >") + "\n\n")
	b.WriteString(th.hint.Render("h/l or arrows to change  |  esc: back"))
	return b.String()
}
