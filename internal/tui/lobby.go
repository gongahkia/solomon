package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/gongahkia/monke/internal/multiplayer"
)

type lobbyState int

const (
	lobbyConnect lobbyState = iota
	lobbyWaiting
)

type serverMsg multiplayer.Message

func listenServer(client *multiplayer.Client) tea.Cmd {
	return func() tea.Msg {
		select {
		case msg := <-client.Recv():
			return serverMsg(msg)
		case <-client.Done():
			return switchStateMsg{state: stateMenu}
		}
	}
}

type LobbyModel struct {
	state     lobbyState
	client    *multiplayer.Client
	addrInput textinput.Model
	nameInput textinput.Model
	codeInput textinput.Model
	focus     int // 0=addr, 1=name, 2=code
	roomCode  string
	players   []string
	err       string
}

func newLobby() LobbyModel {
	addr := textinput.New()
	addr.Placeholder = "localhost:8080"
	addr.Focus()
	addr.CharLimit = 50
	name := textinput.New()
	name.Placeholder = "your name"
	name.CharLimit = 20
	code := textinput.New()
	code.Placeholder = "room code (empty = new)"
	code.CharLimit = 6
	return LobbyModel{
		state:     lobbyConnect,
		addrInput: addr,
		nameInput: name,
		codeInput: code,
	}
}

func (m LobbyModel) Update(msg tea.Msg) (LobbyModel, tea.Cmd) {
	switch msg := msg.(type) {
	case serverMsg:
		sm := multiplayer.Message(msg)
		switch sm.Type {
		case multiplayer.MsgRoomInfo:
			info, _ := multiplayer.DecodePayload[multiplayer.RoomInfoPayload](sm)
			m.roomCode = info.Code
			m.players = info.Players
			m.state = lobbyWaiting
		case multiplayer.MsgCountdown:
			cd, _ := multiplayer.DecodePayload[multiplayer.CountdownPayload](sm)
			m.err = fmt.Sprintf("starting in %d...", cd.Seconds)
		case multiplayer.MsgStart:
			start, _ := multiplayer.DecodePayload[multiplayer.StartPayload](sm)
			return m, func() tea.Msg {
				return startRaceMsg{client: m.client, words: start.Words}
			}
		case multiplayer.MsgError:
			e, _ := multiplayer.DecodePayload[multiplayer.ErrorPayload](sm)
			m.err = e.Message
		}
		if m.client != nil {
			return m, listenServer(m.client)
		}
		return m, nil
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c":
			return m, tea.Quit
		case "esc":
			if m.client != nil {
				m.client.Close()
			}
			return m, func() tea.Msg { return switchStateMsg{state: stateMenu} }
		case "tab":
			if m.state == lobbyConnect {
				m.focus = (m.focus + 1) % 3
				m.addrInput.Blur()
				m.nameInput.Blur()
				m.codeInput.Blur()
				switch m.focus {
				case 0:
					m.addrInput.Focus()
				case 1:
					m.nameInput.Focus()
				case 2:
					m.codeInput.Focus()
				}
			}
		case "enter":
			if m.state == lobbyConnect {
				return m.connect()
			}
			if m.state == lobbyWaiting && m.client != nil {
				_ = m.client.Send(multiplayer.MsgReady, nil)
			}
		}
	}
	var cmd tea.Cmd
	if m.state == lobbyConnect {
		switch m.focus {
		case 0:
			m.addrInput, cmd = m.addrInput.Update(msg)
		case 1:
			m.nameInput, cmd = m.nameInput.Update(msg)
		case 2:
			m.codeInput, cmd = m.codeInput.Update(msg)
		}
	}
	return m, cmd
}

func (m LobbyModel) connect() (LobbyModel, tea.Cmd) {
	addr := m.addrInput.Value()
	if addr == "" {
		addr = "localhost:8080"
	}
	name := m.nameInput.Value()
	if name == "" {
		name = "anon"
	}
	code := strings.ToUpper(strings.TrimSpace(m.codeInput.Value()))
	client, err := multiplayer.Connect(addr, code, name)
	if err != nil {
		m.err = fmt.Sprintf("connect failed: %v", err)
		return m, nil
	}
	m.client = client
	m.err = ""
	return m, listenServer(client)
}

func (m LobbyModel) View() string {
	var b strings.Builder
	b.WriteString(th.title.Render("M O N K E  multiplayer") + "\n\n")
	if m.state == lobbyConnect {
		fields := []struct {
			label string
			input textinput.Model
		}{
			{"server", m.addrInput},
			{"name", m.nameInput},
			{"room code", m.codeInput},
		}
		for i, f := range fields {
			cursor := "  "
			if i == m.focus {
				cursor = th.accent.Render("> ")
			}
			b.WriteString(fmt.Sprintf("%s%s: %s\n", cursor, th.subtitle.Render(f.label), f.input.View()))
		}
		b.WriteString("\n" + th.hint.Render("tab: next field  |  enter: connect  |  esc: back"))
	} else {
		b.WriteString(th.accent.Render(fmt.Sprintf("  room: %s", m.roomCode)) + "\n\n")
		b.WriteString(th.subtitle.Render("  players:") + "\n")
		for _, p := range m.players {
			b.WriteString(th.bold.Render(fmt.Sprintf("    %s", p)) + "\n")
		}
		b.WriteString("\n" + th.hint.Render("enter: ready  |  esc: leave"))
	}
	if m.err != "" {
		b.WriteString("\n\n" + th.incorrect.Render("  "+m.err))
	}
	return b.String()
}
