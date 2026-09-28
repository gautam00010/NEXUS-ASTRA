// Package router provides WebSocket connection management and message broadcasting
// for the NEXUS-ASTRA Go router sidecar.
package router

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// ConnState represents the lifecycle state of a managed WebSocket connection.
type ConnState int

const (
	// StateDisconnected indicates the connection is not active.
	StateDisconnected ConnState = iota
	// StateConnecting indicates a connection attempt is in progress.
	StateConnecting
	// StateConnected indicates the connection is active and healthy.
	StateConnected
	// StateReconnecting indicates the connection dropped and a reconnect is underway.
	StateReconnecting
)

func (s ConnState) String() string {
	switch s {
	case StateDisconnected:
		return "disconnected"
	case StateConnecting:
		return "connecting"
	case StateConnected:
		return "connected"
	case StateReconnecting:
		return "reconnecting"
	default:
		return "unknown"
	}
}

const (
	// maxBackoff is the ceiling for exponential reconnection delay.
	maxBackoff = 60 * time.Second
	// baseBackoff is the initial reconnection delay.
	baseBackoff = 1 * time.Second
	// healthCheckInterval is how often ping/pong health checks run.
	healthCheckInterval = 30 * time.Second
	// pongTimeout is the deadline for receiving a pong after a ping.
	pongTimeout = 10 * time.Second
)

// ManagedConn wraps a single WebSocket connection with state tracking,
// auto-reconnect, and health checks.
type ManagedConn struct {
	mu       sync.RWMutex
	name     string
	url      string
	conn     *websocket.Conn
	state    ConnState
	attempts int
	logger   *slog.Logger
}

// ConnectionPool manages multiple named WebSocket connections concurrently.
// It provides auto-reconnect with exponential backoff and periodic health checks.
type ConnectionPool struct {
	mu    sync.RWMutex
	conns map[string]*ManagedConn
	logger *slog.Logger
}

// NewConnectionPool creates a new, empty connection pool.
func NewConnectionPool(logger *slog.Logger) *ConnectionPool {
	return &ConnectionPool{
		conns:  make(map[string]*ManagedConn),
		logger: logger,
	}
}

// Add registers a new named connection target. It does not dial immediately;
// use Connect to start the connection lifecycle.
func (p *ConnectionPool) Add(name, url string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.conns[name] = &ManagedConn{
		name:   name,
		url:    url,
		state:  StateDisconnected,
		logger: p.logger.With("conn", name),
	}
}

// Connect dials the named WebSocket endpoint and starts the read loop.
// msgHandler is called for every message received on the connection.
// The connection will auto-reconnect on failure until ctx is cancelled.
func (p *ConnectionPool) Connect(ctx context.Context, name string, msgHandler func([]byte)) error {
	p.mu.RLock()
	mc, ok := p.conns[name]
	p.mu.RUnlock()
	if !ok {
		return fmt.Errorf("connection %q not registered in pool", name)
	}

	go mc.runLoop(ctx, msgHandler)
	return nil
}

// GetState returns the current state of a named connection.
func (p *ConnectionPool) GetState(name string) ConnState {
	p.mu.RLock()
	mc, ok := p.conns[name]
	p.mu.RUnlock()
	if !ok {
		return StateDisconnected
	}
	mc.mu.RLock()
	defer mc.mu.RUnlock()
	return mc.state
}

// States returns a snapshot of all connection states.
func (p *ConnectionPool) States() map[string]string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	out := make(map[string]string, len(p.conns))
	for name, mc := range p.conns {
		mc.mu.RLock()
		out[name] = mc.state.String()
		mc.mu.RUnlock()
	}
	return out
}

// Close gracefully shuts down all connections in the pool.
func (p *ConnectionPool) Close() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, mc := range p.conns {
		mc.close()
	}
}

// runLoop manages the full lifecycle of a single connection:
// dial → read → reconnect on error. It exits when ctx is cancelled.
func (mc *ManagedConn) runLoop(ctx context.Context, handler func([]byte)) {
	for {
		select {
		case <-ctx.Done():
			mc.close()
			mc.logger.Info("connection loop stopped", "reason", ctx.Err())
			return
		default:
		}

		if err := mc.dial(ctx); err != nil {
			mc.logger.Error("dial failed", "err", err, "attempt", mc.attempts)
			mc.waitBackoff(ctx)
			continue
		}

		// Reset attempt counter on successful connect.
		mc.mu.Lock()
		mc.attempts = 0
		mc.mu.Unlock()

		mc.readLoop(ctx, handler)

		// If we exit readLoop, the connection dropped. Reconnect unless cancelled.
		select {
		case <-ctx.Done():
			mc.close()
			return
		default:
			mc.setState(StateReconnecting)
			mc.logger.Warn("connection lost, reconnecting")
		}
	}
}

// dial establishes the WebSocket connection with a timeout.
func (mc *ManagedConn) dial(ctx context.Context) error {
	mc.setState(StateConnecting)

	dialer := websocket.Dialer{
		HandshakeTimeout: 15 * time.Second,
	}

	conn, _, err := dialer.DialContext(ctx, mc.url, nil)
	if err != nil {
		mc.setState(StateDisconnected)
		mc.mu.Lock()
		mc.attempts++
		mc.mu.Unlock()
		return fmt.Errorf("websocket dial %s: %w", mc.url, err)
	}

	mc.mu.Lock()
	mc.conn = conn
	mc.mu.Unlock()
	mc.setState(StateConnected)
	mc.logger.Info("connected", "url", mc.url)

	// Configure pong handler for health checks.
	conn.SetPongHandler(func(appData string) error {
		return conn.SetReadDeadline(time.Now().Add(healthCheckInterval + pongTimeout))
	})

	return nil
}

// readLoop reads messages from the connection and dispatches them to handler.
// It also runs periodic ping health checks. Returns when the connection fails.
func (mc *ManagedConn) readLoop(ctx context.Context, handler func([]byte)) {
	mc.mu.RLock()
	conn := mc.conn
	mc.mu.RUnlock()
	if conn == nil {
		return
	}

	// Start health-check pinger in background.
	pingCtx, pingCancel := context.WithCancel(ctx)
	defer pingCancel()
	go mc.healthChecker(pingCtx, conn)

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		_, msg, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				mc.logger.Error("read error", "err", err)
			}
			return
		}

		handler(msg)
	}
}

// healthChecker sends periodic WebSocket pings to verify the connection is alive.
func (mc *ManagedConn) healthChecker(ctx context.Context, conn *websocket.Conn) {
	ticker := time.NewTicker(healthCheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			mc.mu.RLock()
			currentConn := mc.conn
			mc.mu.RUnlock()

			// Don't ping a stale or replaced connection.
			if currentConn != conn {
				return
			}

			if err := conn.WriteControl(
				websocket.PingMessage,
				[]byte("ping"),
				time.Now().Add(pongTimeout),
			); err != nil {
				mc.logger.Warn("health check ping failed", "err", err)
				return
			}
			mc.logger.Debug("health check ping sent")
		}
	}
}

// waitBackoff sleeps for an exponentially increasing duration, capped at maxBackoff.
func (mc *ManagedConn) waitBackoff(ctx context.Context) {
	mc.mu.RLock()
	attempt := mc.attempts
	mc.mu.RUnlock()

	delay := baseBackoff * time.Duration(math.Pow(2, float64(attempt-1)))
	if delay > maxBackoff {
		delay = maxBackoff
	}

	mc.logger.Info("backing off before reconnect", "delay", delay)
	select {
	case <-ctx.Done():
	case <-time.After(delay):
	}
}

// setState updates the connection state in a thread-safe manner.
func (mc *ManagedConn) setState(s ConnState) {
	mc.mu.Lock()
	mc.state = s
	mc.mu.Unlock()
}

// close gracefully closes the underlying WebSocket connection.
func (mc *ManagedConn) close() {
	mc.mu.Lock()
	defer mc.mu.Unlock()
	if mc.conn != nil {
		_ = mc.conn.WriteMessage(
			websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.CloseNormalClosure, "shutting down"),
		)
		_ = mc.conn.Close()
		mc.conn = nil
	}
	mc.state = StateDisconnected
}
