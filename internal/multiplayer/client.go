package multiplayer

import (
	"context"

	"nhooyr.io/websocket"
)

type Client struct {
	conn     *websocket.Conn
	PlayerID string
	Name     string
	recvCh   chan Message
	done     chan struct{}
	ctx      context.Context
	cancel   context.CancelFunc
}

func Connect(addr, roomCode, name string) (*Client, error) {
	ctx, cancel := context.WithCancel(context.Background())
	conn, _, err := websocket.Dial(ctx, "ws://"+addr+"/ws", nil)
	if err != nil {
		cancel()
		return nil, err
	}
	c := &Client{
		conn:   conn,
		Name:   name,
		recvCh: make(chan Message, 64),
		done:   make(chan struct{}),
		ctx:    ctx,
		cancel: cancel,
	}
	// send join
	data, err := Encode(MsgJoin, JoinPayload{RoomCode: roomCode, Name: name})
	if err != nil {
		conn.CloseNow()
		cancel()
		return nil, err
	}
	if err := conn.Write(ctx, websocket.MessageText, data); err != nil {
		conn.CloseNow()
		cancel()
		return nil, err
	}
	go c.readLoop()
	return c, nil
}

func (c *Client) readLoop() {
	defer close(c.done)
	for {
		_, data, err := c.conn.Read(c.ctx)
		if err != nil {
			return
		}
		msg, err := Decode(data)
		if err != nil {
			continue
		}
		select {
		case c.recvCh <- msg:
		default: // drop if full
		}
	}
}

func (c *Client) Send(msgType MsgType, payload interface{}) error {
	data, err := Encode(msgType, payload)
	if err != nil {
		return err
	}
	return c.conn.Write(c.ctx, websocket.MessageText, data)
}

func (c *Client) Recv() <-chan Message { return c.recvCh }
func (c *Client) Done() <-chan struct{} { return c.done }

func (c *Client) Close() {
	c.cancel()
	c.conn.Close(websocket.StatusNormalClosure, "bye")
}
