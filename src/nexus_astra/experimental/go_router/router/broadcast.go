package router

import (
	"log/slog"
	"sync"
)

const (
	// defaultBufferSize is the channel buffer size per subscriber.
	// Sized to absorb short bursts without blocking the publisher.
	defaultBufferSize = 256
)

// Subscriber represents a single consumer registered to a Broadcaster topic.
type Subscriber struct {
	// ID is a unique identifier for this subscriber.
	ID string
	// C is the channel on which the subscriber receives messages.
	C chan []byte
}

// Broadcaster provides fan-out message distribution from data feeds to
// multiple Python consumers. It uses buffered Go channels with non-blocking
// sends to ensure a slow subscriber cannot stall the entire pipeline.
type Broadcaster struct {
	mu          sync.RWMutex
	subscribers map[string]map[string]*Subscriber // topic -> subscriberID -> Subscriber
	logger      *slog.Logger
}

// NewBroadcaster creates a new Broadcaster instance.
func NewBroadcaster(logger *slog.Logger) *Broadcaster {
	return &Broadcaster{
		subscribers: make(map[string]map[string]*Subscriber),
		logger:      logger,
	}
}

// Subscribe registers a new subscriber for the given topic and returns a
// Subscriber handle. The caller should read from Subscriber.C to receive
// messages. Call Unsubscribe when done.
func (b *Broadcaster) Subscribe(topic, id string) *Subscriber {
	b.mu.Lock()
	defer b.mu.Unlock()

	if _, ok := b.subscribers[topic]; !ok {
		b.subscribers[topic] = make(map[string]*Subscriber)
	}

	sub := &Subscriber{
		ID: id,
		C:  make(chan []byte, defaultBufferSize),
	}
	b.subscribers[topic][id] = sub

	b.logger.Info("subscriber registered", "topic", topic, "id", id)
	return sub
}

// Unsubscribe removes a subscriber from the given topic and closes its channel.
func (b *Broadcaster) Unsubscribe(topic, id string) {
	b.mu.Lock()
	defer b.mu.Unlock()

	topicSubs, ok := b.subscribers[topic]
	if !ok {
		return
	}

	sub, ok := topicSubs[id]
	if !ok {
		return
	}

	close(sub.C)
	delete(topicSubs, id)

	if len(topicSubs) == 0 {
		delete(b.subscribers, topic)
	}

	b.logger.Info("subscriber unregistered", "topic", topic, "id", id)
}

// Publish sends a message to all subscribers of the given topic.
// Uses non-blocking sends: if a subscriber's buffer is full, the message
// is dropped for that subscriber and a warning is logged. This prevents
// a slow consumer from blocking the entire feed pipeline.
func (b *Broadcaster) Publish(topic string, msg []byte) {
	b.mu.RLock()
	defer b.mu.RUnlock()

	topicSubs, ok := b.subscribers[topic]
	if !ok {
		return
	}

	for _, sub := range topicSubs {
		select {
		case sub.C <- msg:
			// Delivered successfully.
		default:
			// Buffer full — drop message for this subscriber to protect the pipeline.
			b.logger.Warn("subscriber buffer full, message dropped",
				"topic", topic,
				"subscriber", sub.ID,
				"bufferSize", defaultBufferSize,
			)
		}
	}
}

// TopicSubscriberCount returns the number of active subscribers for a topic.
func (b *Broadcaster) TopicSubscriberCount(topic string) int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.subscribers[topic])
}

// Close shuts down the broadcaster, closing all subscriber channels.
func (b *Broadcaster) Close() {
	b.mu.Lock()
	defer b.mu.Unlock()

	for topic, subs := range b.subscribers {
		for id, sub := range subs {
			close(sub.C)
			b.logger.Debug("closed subscriber channel", "topic", topic, "id", id)
		}
	}
	b.subscribers = make(map[string]map[string]*Subscriber)
	b.logger.Info("broadcaster shut down")
}
