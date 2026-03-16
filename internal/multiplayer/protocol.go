package multiplayer

import "encoding/json"

type MsgType string

const (
	MsgJoin       MsgType = "join"
	MsgReady      MsgType = "ready"
	MsgCountdown  MsgType = "countdown"
	MsgStart      MsgType = "start"
	MsgProgress   MsgType = "progress"
	MsgFinish     MsgType = "finish"
	MsgResult     MsgType = "result"
	MsgDisconnect MsgType = "disconnect"
	MsgRoomInfo   MsgType = "room_info"
	MsgError      MsgType = "error"
)

type Message struct {
	Type    MsgType         `json:"type"`
	Payload json.RawMessage `json:"payload"`
}

type JoinPayload struct {
	RoomCode string `json:"room_code"` // empty = create new
	Name     string `json:"name"`
}

type ProgressPayload struct {
	PlayerID   string  `json:"player_id"`
	Name       string  `json:"name"`
	CharsTyped int     `json:"chars_typed"`
	TotalChars int     `json:"total_chars"`
	WPM        float64 `json:"wpm"`
	Finished   bool    `json:"finished"`
}

type CountdownPayload struct {
	Seconds int `json:"seconds"`
}

type StartPayload struct {
	Words []string `json:"words"`
}

type RoomInfoPayload struct {
	Code    string   `json:"code"`
	Players []string `json:"players"`
}

type ResultPayload struct {
	Rankings []PlayerResult `json:"rankings"`
}

type PlayerResult struct {
	Name     string  `json:"name"`
	WPM      float64 `json:"wpm"`
	Accuracy float64 `json:"accuracy"`
	Place    int     `json:"place"`
}

type ErrorPayload struct {
	Message string `json:"message"`
}

func Encode(msgType MsgType, payload interface{}) ([]byte, error) {
	p, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	return json.Marshal(Message{Type: msgType, Payload: p})
}

func Decode(data []byte) (Message, error) {
	var m Message
	err := json.Unmarshal(data, &m)
	return m, err
}

func DecodePayload[T any](m Message) (T, error) {
	var v T
	err := json.Unmarshal(m.Payload, &v)
	return v, err
}
