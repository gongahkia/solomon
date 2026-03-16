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
	lobby    LobbyModel
	race     RaceModel
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
		switch msg.state {
		case stateMenu:
			m.menu = newMenu()
		case stateSettings:
			m.settings = newSettings(m.cfg)
		case stateLobby:
			m.lobby = newLobby()
		}
		m.state = msg.state
		return m, nil
	case startTypingMsg:
		typing, cmd := newTyping(msg.config)
		typing.width = m.width
		typing.height = m.height
		m.typing = typing
		m.state = stateTyping
		return m, cmd
	case startRaceMsg:
		race, cmd := newRace(msg.client, msg.words)
		race.width = m.width
		race.height = m.height
		m.race = race
		m.state = stateRace
		return m, cmd
	case showResultsMsg:
		m.results = newResults(msg.result, msg.config)
		if m.store != nil {
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
	case stateLobby:
		m.lobby, cmd = m.lobby.Update(msg)
	case stateRace:
		m.race, cmd = m.race.Update(msg)
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
	case stateLobby:
		content = m.lobby.View()
	case stateRace:
		content = m.race.View()
	default:
		content = th.dim.Render("not implemented yet")
	}
	return lipgloss.NewStyle().
		Padding(1, 2).
		MaxWidth(m.width).
		MaxHeight(m.height).
		Render(content)
}
