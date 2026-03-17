package multiplayer

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math/rand/v2"
	"net/http"
	"sort"
	"sync"
	"time"

	"nhooyr.io/websocket"
)

type Server struct {
	rooms    map[string]*Room
	mu       sync.RWMutex
	wordPool []string
}

func NewServer(words []string) *Server {
	return &Server{
		rooms:    make(map[string]*Room),
		wordPool: words,
	}
}

func (s *Server) Run(addr string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", s.handleWS)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("ok"))
	})
	go s.cleanup()
	log.Printf("monke-server listening on %s", addr)
	return http.ListenAndServe(addr, mux)
}

func (s *Server) cleanup() {
	for {
		time.Sleep(time.Minute)
		s.mu.Lock()
		for code, room := range s.rooms {
			if room.IsEmpty() || time.Since(room.CreatedAt) > 30*time.Minute {
				delete(s.rooms, code)
			}
		}
		s.mu.Unlock()
	}
}

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		log.Printf("ws accept: %v", err)
		return
	}
	defer conn.CloseNow()
	ctx := r.Context()
	// read first message (must be join)
	_, data, err := conn.Read(ctx)
	if err != nil {
		return
	}
	msg, err := Decode(data)
	if err != nil || msg.Type != MsgJoin {
		s.sendError(ctx, conn, "first message must be join")
		return
	}
	join, err := DecodePayload[JoinPayload](msg)
	if err != nil {
		s.sendError(ctx, conn, "invalid join payload")
		return
	}
	playerID := fmt.Sprintf("%d", time.Now().UnixNano())
	player := &Player{ID: playerID, Name: join.Name, Conn: conn}
	var room *Room
	if join.RoomCode == "" { // create new room
		room = NewRoom()
		s.mu.Lock()
		s.rooms[room.Code] = room
		s.mu.Unlock()
	} else { // join existing
		s.mu.RLock()
		room = s.rooms[join.RoomCode]
		s.mu.RUnlock()
		if room == nil {
			s.sendError(ctx, conn, "room not found")
			return
		}
	}
	if !room.AddPlayer(player) {
		s.sendError(ctx, conn, "room full or already started")
		return
	}
	defer func() {
		room.RemovePlayer(playerID)
		s.broadcastRoomInfo(ctx, room)
	}()
	s.broadcastRoomInfo(ctx, room)
	// main message loop
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			return
		}
		msg, err := Decode(data)
		if err != nil {
			continue
		}
		switch msg.Type {
		case MsgReady:
			room.mu.Lock()
			if p, ok := room.Players[playerID]; ok {
				p.Ready = true
			}
			room.mu.Unlock()
			if room.AllReady() {
				go s.startCountdown(ctx, room)
			}
		case MsgProgress:
			prog, err := DecodePayload[ProgressPayload](msg)
			if err != nil {
				continue
			}
			prog.PlayerID = playerID
			prog.Name = player.Name
			room.UpdateProgress(playerID, prog)
			s.broadcastProgress(ctx, room)
			if room.AllFinished() {
				s.broadcastResults(ctx, room)
			}
		case MsgFinish:
			room.mu.Lock()
			if p, ok := room.Players[playerID]; ok {
				p.Done = true
			}
			room.mu.Unlock()
			if room.AllFinished() {
				s.broadcastResults(ctx, room)
			}
		}
	}
}

func (s *Server) startCountdown(ctx context.Context, room *Room) {
	room.mu.Lock()
	if room.State != RoomWaiting {
		room.mu.Unlock()
		return
	}
	room.State = RoomCountdown
	room.mu.Unlock()
	for i := 5; i > 0; i-- {
		s.broadcast(ctx, room, MsgCountdown, CountdownPayload{Seconds: i})
		time.Sleep(time.Second)
	}
	// generate words for race
	words := make([]string, 100)
	for i := range words {
		words[i] = s.wordPool[rand.IntN(len(s.wordPool))]
	}
	room.mu.Lock()
	room.Words = words
	room.State = RoomRacing
	room.mu.Unlock()
	s.broadcast(ctx, room, MsgStart, StartPayload{Words: words})
}

func (s *Server) broadcastRoomInfo(ctx context.Context, room *Room) {
	s.broadcast(ctx, room, MsgRoomInfo, RoomInfoPayload{
		Code:    room.Code,
		Players: room.PlayerNames(),
	})
}

func (s *Server) broadcastProgress(ctx context.Context, room *Room) {
	room.mu.Lock()
	var progs []ProgressPayload
	for _, p := range room.Players {
		progs = append(progs, p.Progress)
	}
	room.mu.Unlock()
	for _, prog := range progs {
		s.broadcast(ctx, room, MsgProgress, prog)
	}
}

func (s *Server) broadcastResults(ctx context.Context, room *Room) {
	room.mu.Lock()
	room.State = RoomFinished
	var results []PlayerResult
	for _, p := range room.Players {
		results = append(results, PlayerResult{
			Name:     p.Name,
			WPM:      p.Progress.WPM,
			Accuracy: p.Progress.Accuracy,
		})
	}
	room.mu.Unlock()
	sort.Slice(results, func(i, j int) bool { return results[i].WPM > results[j].WPM })
	for i := range results {
		results[i].Place = i + 1
	}
	s.broadcast(ctx, room, MsgResult, ResultPayload{Rankings: results})
}

func (s *Server) broadcast(ctx context.Context, room *Room, msgType MsgType, payload interface{}) {
	data, err := Encode(msgType, payload)
	if err != nil {
		return
	}
	room.mu.Lock()
	defer room.mu.Unlock()
	for _, p := range room.Players {
		_ = p.Conn.Write(ctx, websocket.MessageText, data)
	}
}

func (s *Server) sendError(ctx context.Context, conn *websocket.Conn, msg string) {
	data, _ := json.Marshal(Message{
		Type:    MsgError,
		Payload: json.RawMessage(fmt.Sprintf(`{"message":"%s"}`, msg)),
	})
	conn.Write(ctx, websocket.MessageText, data)
}
