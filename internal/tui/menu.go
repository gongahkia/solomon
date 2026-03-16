package tui

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

type menuState int

const (
	menuMain menuState = iota
	menuMode
	menuTime
	menuWords
	menuWordList
)

type MenuModel struct {
	state    menuState
	cursor   int
	mode     string // "time" or "words"
	param    int    // seconds or word count
	wordList string
}

func newMenu() MenuModel {
	return MenuModel{wordList: "english_200"}
}

var (
	mainChoices    = []string{"singleplayer", "multiplayer", "settings", "quit"}
	modeChoices    = []string{"time", "words"}
	timeChoices    = []int{15, 30, 60, 120}
	wordChoices    = []int{10, 25, 50, 100}
)

func (m MenuModel) Init() tea.Cmd { return nil }

func (m MenuModel) Update(msg tea.Msg) (MenuModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j":
			if m.cursor < m.choiceCount()-1 {
				m.cursor++
			}
		case "enter":
			return m.select_()
		case "esc":
			if m.state != menuMain {
				m.state = menuMain
				m.cursor = 0
			}
		}
	}
	return m, nil
}

func (m MenuModel) choiceCount() int {
	switch m.state {
	case menuMain:
		return len(mainChoices)
	case menuMode:
		return len(modeChoices)
	case menuTime:
		return len(timeChoices)
	case menuWords:
		return len(wordChoices)
	case menuWordList:
		lists := availableWordLists
		if len(lists) == 0 {
			return 1
		}
		return len(lists)
	}
	return 0
}

var availableWordLists []string

func (m MenuModel) select_() (MenuModel, tea.Cmd) {
	switch m.state {
	case menuMain:
		switch m.cursor {
		case 0: // singleplayer
			m.state = menuMode
			m.cursor = 0
		case 1: // multiplayer
			return m, func() tea.Msg { return switchStateMsg{state: stateLobby} }
		case 2: // settings
			return m, func() tea.Msg { return switchStateMsg{state: stateSettings} }
		case 3: // quit
			return m, tea.Quit
		}
	case menuMode:
		m.mode = modeChoices[m.cursor]
		if m.mode == "time" {
			m.state = menuTime
		} else {
			m.state = menuWords
		}
		m.cursor = 1 // default to 30s or 25 words
	case menuTime:
		m.param = timeChoices[m.cursor]
		m.state = menuWordList
		m.cursor = 0
	case menuWords:
		m.param = wordChoices[m.cursor]
		m.state = menuWordList
		m.cursor = 0
	case menuWordList:
		lists := availableWordLists
		if len(lists) > 0 {
			m.wordList = lists[m.cursor]
		}
		cfg := typingConfig{Mode: m.mode, Param: m.param, WordList: m.wordList}
		m.state = menuMain
		m.cursor = 0
		return m, func() tea.Msg { return startTypingMsg{config: cfg} }
	}
	return m, nil
}

func (m MenuModel) View(width int) string {
	var b strings.Builder
	title := th.title.Render("M O N K E")
	b.WriteString(title + "\n\n")
	var choices []string
	var labels []string
	switch m.state {
	case menuMain:
		b.WriteString(th.subtitle.Render("main menu") + "\n\n")
		labels = mainChoices
	case menuMode:
		b.WriteString(th.subtitle.Render("select mode") + "\n\n")
		labels = modeChoices
	case menuTime:
		b.WriteString(th.subtitle.Render("select time") + "\n\n")
		for _, t := range timeChoices {
			labels = append(labels, fmt.Sprintf("%ds", t))
		}
	case menuWords:
		b.WriteString(th.subtitle.Render("select word count") + "\n\n")
		for _, w := range wordChoices {
			labels = append(labels, fmt.Sprintf("%d words", w))
		}
	case menuWordList:
		b.WriteString(th.subtitle.Render("select word list") + "\n\n")
		lists := availableWordLists
		if len(lists) == 0 {
			labels = []string{"english_200"}
		} else {
			labels = lists
		}
	}
	for i, l := range labels {
		cursor := "  "
		style := th.upcoming
		if i == m.cursor {
			cursor = th.accent.Render("> ")
			style = th.bold
		}
		choices = append(choices, cursor+style.Render(l))
	}
	b.WriteString(strings.Join(choices, "\n"))
	b.WriteString("\n\n" + th.hint.Render("j/k or arrows to move • enter to select • esc to go back"))
	return b.String()
}
