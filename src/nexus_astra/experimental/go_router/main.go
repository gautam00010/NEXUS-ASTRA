// Package main implements the NEXUS-ASTRA Go WebSocket router sidecar.
//
// This microservice manages concurrent WebSocket connections to multiple
// financial data feeds (Binance, Zerodha, alternative data), normalizes
// incoming data to JSON, and forwards it to the Python trading process
// via HTTP POST on localhost:8080.
//
// Routes:
//
//	GET  /health        — health check
//	POST /ws/binance    — start Binance futures stream (BTC/ETH funding + OI)
//	POST /ws/zerodha    — start Zerodha Kite NSE tick stream
//	POST /ws/alternative — start alternative data feeds (NewsAPI, Whale Alert)
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/nexus-astra/go-router/router"
)

// Config holds runtime configuration, sourced from environment variables.
type Config struct {
	ListenAddr       string
	PythonUpstream   string
	BinanceWSURL     string
	ZerodhaWSURL     string
	NewsAPIWSURL     string
	WhaleAlertWSURL  string
}

// loadConfig reads configuration from environment variables with sensible defaults.
func loadConfig() Config {
	return Config{
		ListenAddr:      envOrDefault("LISTEN_ADDR", ":9090"),
		PythonUpstream:  envOrDefault("PYTHON_UPSTREAM", "http://localhost:8080"),
		BinanceWSURL:    envOrDefault("BINANCE_WS_URL", "wss://fstream.binance.com/stream?streams=btcusdt@markPrice/ethusdt@markPrice/btcusdt@ticker/ethusdt@ticker"),
		ZerodhaWSURL:    envOrDefault("ZERODHA_WS_URL", "wss://ws.kite.trade"),
		NewsAPIWSURL:    envOrDefault("NEWSAPI_WS_URL", "wss://newsapi.example.com/v1/stream"),
		WhaleAlertWSURL: envOrDefault("WHALEALERT_WS_URL", "wss://whale-alert.io/ws"),
	}
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	// Structured logger — JSON in production for machine parsing.
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	cfg := loadConfig()
	logger.Info("starting NEXUS-ASTRA go-router",
		"listen", cfg.ListenAddr,
		"upstream", cfg.PythonUpstream,
	)

	// Shared infrastructure.
	pool := router.NewConnectionPool(logger)
	broadcaster := router.NewBroadcaster(logger)
	httpClient := &http.Client{Timeout: 5 * time.Second}

	// Context that cancels on SIGINT / SIGTERM for graceful shutdown.
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// --- HTTP routes ---
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", handleHealth(pool))
	mux.HandleFunc("POST /ws/binance", handleBinance(ctx, cfg, pool, broadcaster, httpClient, logger))
	mux.HandleFunc("POST /ws/zerodha", handleZerodha(ctx, cfg, pool, broadcaster, httpClient, logger))
	mux.HandleFunc("POST /ws/alternative", handleAlternative(ctx, cfg, pool, broadcaster, httpClient, logger))

	srv := &http.Server{
		Addr:         cfg.ListenAddr,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Start server in background goroutine.
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		logger.Info("HTTP server listening", "addr", cfg.ListenAddr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("HTTP server error", "err", err)
			cancel()
		}
	}()

	// Block until shutdown signal.
	<-ctx.Done()
	logger.Info("shutdown signal received, draining connections")

	// Graceful shutdown with 10-second deadline.
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	pool.Close()
	broadcaster.Close()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("HTTP server shutdown error", "err", err)
	}

	wg.Wait()
	logger.Info("go-router stopped cleanly")
}

// ---------------------------------------------------------------------------
// HTTP Handlers
// ---------------------------------------------------------------------------

// handleHealth returns a JSON health check including the state of all managed
// WebSocket connections.
func handleHealth(pool *router.ConnectionPool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		resp := map[string]any{
			"status":      "ok",
			"service":     "nexus-astra-go-router",
			"timestamp":   time.Now().UTC().Format(time.RFC3339),
			"connections": pool.States(),
		}
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(resp)
	}
}

// handleBinance starts a WebSocket connection to the Binance futures stream
// for BTC/ETH funding rates and open interest. Normalized JSON messages are
// forwarded to the Python process at /crypto_feed.
func handleBinance(
	ctx context.Context,
	cfg Config,
	pool *router.ConnectionPool,
	broadcaster *router.Broadcaster,
	client *http.Client,
	logger *slog.Logger,
) http.HandlerFunc {
	var once sync.Once
	return func(w http.ResponseWriter, r *http.Request) {
		once.Do(func() {
			pool.Add("binance", cfg.BinanceWSURL)

			forwardURL := cfg.PythonUpstream + "/crypto_feed"
			handler := makeForwardHandler("binance", forwardURL, broadcaster, client, logger)

			if err := pool.Connect(ctx, "binance", handler); err != nil {
				logger.Error("failed to start binance stream", "err", err)
				return
			}
			logger.Info("binance stream started")
		})

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"status": "binance stream active",
			"feed":   cfg.BinanceWSURL,
		})
	}
}

// handleZerodha starts a WebSocket connection to the Zerodha Kite endpoint
// for live NSE tick data. Normalized JSON is forwarded to /nse_tick.
func handleZerodha(
	ctx context.Context,
	cfg Config,
	pool *router.ConnectionPool,
	broadcaster *router.Broadcaster,
	client *http.Client,
	logger *slog.Logger,
) http.HandlerFunc {
	var once sync.Once
	return func(w http.ResponseWriter, r *http.Request) {
		once.Do(func() {
			pool.Add("zerodha", cfg.ZerodhaWSURL)

			forwardURL := cfg.PythonUpstream + "/nse_tick"
			handler := makeForwardHandler("zerodha", forwardURL, broadcaster, client, logger)

			if err := pool.Connect(ctx, "zerodha", handler); err != nil {
				logger.Error("failed to start zerodha stream", "err", err)
				return
			}
			logger.Info("zerodha stream started")
		})

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"status": "zerodha stream active",
			"feed":   cfg.ZerodhaWSURL,
		})
	}
}

// handleAlternative starts connections to alternative data feeds (NewsAPI,
// Whale Alert). All messages are forwarded to /alt_feed.
func handleAlternative(
	ctx context.Context,
	cfg Config,
	pool *router.ConnectionPool,
	broadcaster *router.Broadcaster,
	client *http.Client,
	logger *slog.Logger,
) http.HandlerFunc {
	var once sync.Once
	return func(w http.ResponseWriter, r *http.Request) {
		once.Do(func() {
			forwardURL := cfg.PythonUpstream + "/alt_feed"
			handler := makeForwardHandler("alternative", forwardURL, broadcaster, client, logger)

			pool.Add("newsapi", cfg.NewsAPIWSURL)
			pool.Add("whalealert", cfg.WhaleAlertWSURL)

			if err := pool.Connect(ctx, "newsapi", handler); err != nil {
				logger.Error("failed to start newsapi stream", "err", err)
			}
			if err := pool.Connect(ctx, "whalealert", handler); err != nil {
				logger.Error("failed to start whalealert stream", "err", err)
			}
			logger.Info("alternative data streams started")
		})

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"status": "alternative streams active",
		})
	}
}

// ---------------------------------------------------------------------------
// Feed forwarding
// ---------------------------------------------------------------------------

// NormalizedMessage is the envelope sent to the Python upstream for every
// incoming WebSocket message.
type NormalizedMessage struct {
	Source    string          `json:"source"`
	Received string          `json:"received"`
	Data     json.RawMessage `json:"data"`
}

// makeForwardHandler returns a function that normalizes raw WebSocket bytes
// into a NormalizedMessage and POSTs it to the Python upstream. It also
// publishes to the broadcaster for any additional subscribers.
func makeForwardHandler(
	source string,
	forwardURL string,
	broadcaster *router.Broadcaster,
	client *http.Client,
	logger *slog.Logger,
) func([]byte) {
	return func(raw []byte) {
		// Attempt to validate that the payload is JSON; if not, wrap it.
		var data json.RawMessage
		if json.Valid(raw) {
			data = raw
		} else {
			// Wrap non-JSON payloads (e.g. Zerodha binary ticks) as a base64-ish string.
			wrapped, _ := json.Marshal(string(raw))
			data = wrapped
		}

		msg := NormalizedMessage{
			Source:   source,
			Received: time.Now().UTC().Format(time.RFC3339Nano),
			Data:     data,
		}

		payload, err := json.Marshal(msg)
		if err != nil {
			logger.Error("failed to marshal normalized message", "source", source, "err", err)
			return
		}

		// Fan-out to any registered broadcaster subscribers.
		broadcaster.Publish(source, payload)

		// Forward to Python upstream.
		resp, err := client.Post(forwardURL, "application/json", bytes.NewReader(payload))
		if err != nil {
			logger.Warn("upstream POST failed",
				"source", source,
				"url", forwardURL,
				"err", err,
			)
			return
		}
		defer resp.Body.Close()

		if resp.StatusCode >= 400 {
			logger.Warn("upstream returned error",
				"source", source,
				"url", forwardURL,
				"status", resp.StatusCode,
			)
		} else {
			logger.Debug("forwarded to upstream",
				"source", source,
				"url", forwardURL,
				"status", resp.StatusCode,
				"size", len(payload),
			)
		}
	}
}

// formatErr is a helper for writing JSON error responses.
func formatErr(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error": msg,
	})
}

// unused but kept for future route expansion.
var _ = fmt.Sprintf
