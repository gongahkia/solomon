package multiplayer

import (
	"math/rand/v2"
	"sync"
	"time"

	"nhooyr.io/websocket"
)

type RoomState int

const (
	RoomWaiting RoomState = iota
	RoomCountdown
	RoomRacing
	RoomFinished
)

type Player struct {
	ID       string
	Name     string
	Conn     *websocket.Conn
	Progress ProgressPayload
	Ready    bool
	Done     bool
}

type Room struct {
	Code         string
	State        RoomState
	Players      map[string]*Player
	Words        []string
	CreatedAt    time.Time
	resultsSent  bool
	mu           sync.Mutex
}

func generateCode() string {
	const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" // no ambiguous chars
	code := make([]byte, 6)
	for i := range code {
		code[i] = chars[rand.IntN(len(chars))]
	}
	return string(code)
}

func NewRoom() *Room {
	return &Room{
		Code:      generateCode(),
		State:     RoomWaiting,
		Players:   make(map[string]*Player),
		CreatedAt: time.Now(),
	}
}

func (r *Room) AddPlayer(p *Player) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.Players) >= 5 || r.State != RoomWaiting {
		return false
	}
	r.Players[p.ID] = p
	return true
}

func (r *Room) RemovePlayer(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.Players, id)
}

func (r *Room) PlayerNames() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	var names []string
	for _, p := range r.Players {
		names = append(names, p.Name)
	}
	return names
}

func (r *Room) AllReady() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.Players) < 2 {
		return false
	}
	for _, p := range r.Players {
		if !p.Ready {
			return false
		}
	}
	return true
}

func (r *Room) AllFinished() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.resultsSent {
		return false // already broadcast, prevent double send
	}
	for _, p := range r.Players {
		if !p.Done {
			return false
		}
	}
	r.resultsSent = true
	return true
}

func (r *Room) UpdateProgress(id string, prog ProgressPayload) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if p, ok := r.Players[id]; ok {
		p.Progress = prog
		if prog.Finished {
			p.Done = true
		}
	}
}

func (r *Room) IsEmpty() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.Players) == 0
}
