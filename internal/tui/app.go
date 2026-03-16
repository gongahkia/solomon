package tui

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/gongahkia/monke/internal/config"
	"github.com/gongahkia/monke/internal/store"
	"github.com/gongahkia/monke/internal/wordlist"
)

type appState int

const (
	stateMenu appState = iota
	stateTyping
	stateResults
	stateSettings
	stateLobby
	stateRace
)

type switchStateMsg struct{ state appState }
type startTypingMsg struct{ config typingConfig }

type AppModel struct {
	state    appState
	menu     MenuModel
	typing   TypingModel
	results  ResultsModel
	settings SettingsModel
	cfg      *config.Config
	store    *store.Store
	width    int
	height   int
}

func NewApp(cfg *config.Config, st *store.Store) AppModel {
	availableWordLists = wordlist.Available()
	applyTheme(cfg.Theme)
	return AppModel{
		state: stateMenu,
		menu:  newMenu(),
		cfg:   cfg,
		store: st,
		width: 80, height: 24,
	}
}

func (m AppModel) Init() tea.Cmd { return nil }

func (m AppModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
	case switchStateMsg:
		m.state = msg.state
		if msg.state == stateMenu {
			m.menu = newMenu()
		}
		if msg.state == stateSettings {
			m.settings = newSettings(m.cfg)
		}
		return m, nil
	case startTypingMsg:
		typing, cmd := newTyping(msg.config)
		typing.width = m.width
		typing.height = m.height
		m.typing = typing
		m.state = stateTyping
		return m, cmd
	case showResultsMsg:
		m.results = newResults(msg.result, msg.config)
		if m.store != nil { // persist result
			tr := store.NewTestResult(
				msg.result.Mode, msg.config.Param, msg.config.WordList,
				msg.result.NetWPM, msg.result.RawWPM, msg.result.Accuracy,
				msg.result.Correct, msg.result.Incorrect, msg.result.ExtraCount, msg.result.Missed,
				msg.result.Consistency,
			)
			isPB := m.store.AddResult(tr)
			_ = m.store.Save()
			m.results.isPB = isPB
		}
		m.state = stateResults
		return m, nil
	case applyThemeMsg:
		applyTheme(msg.name)
		m.cfg.Theme = msg.name
		_ = m.cfg.Save()
		return m, nil
	}
	var cmd tea.Cmd
	switch m.state {
	case stateMenu:
		m.menu, cmd = m.menu.Update(msg)
	case stateTyping:
		m.typing, cmd = m.typing.Update(msg)
	case stateResults:
		m.results, cmd = m.results.Update(msg)
	case stateSettings:
		m.settings, cmd = m.settings.Update(msg)
	}
	return m, cmd
}

func (m AppModel) View() string {
	var content string
	switch m.state {
	case stateMenu:
		content = m.menu.View(m.width)
	case stateTyping:
		content = m.typing.View()
	case stateResults:
		content = m.results.View()
	case stateSettings:
		content = m.settings.View()
	default:
		content = th.dim.Render("not implemented yet")
	}
	return lipgloss.NewStyle().
		Padding(1, 2).
		MaxWidth(m.width).
		MaxHeight(m.height).
		Render(content)
}
