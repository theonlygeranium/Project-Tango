# ADR: Nexus Bus (Redis Streams) for Inter-Bot Communication

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

The Discord bot fleet previously relied on Discord channels for inter-bot
communication. Bots sent messages to shared channels and other bots read
those messages via the Discord gateway. This approach was brittle,
rate-limited, and non-deterministic:

- Discord's 2-second per-channel rate limit caused message delays and 429
  backoff loops during high-volume coordination.
- Message ordering was not guaranteed across channels, causing race
  conditions in task delegation and acknowledgment.
- Discord gateway disconnects silently dropped inter-bot messages with no
  retry or dead-letter mechanism.
- Bot-to-bot messages cluttered user-facing channels, making it difficult
  to distinguish fleet coordination from user conversations.

## Decision

Use **Redis Streams** as the Nexus Bus event transport layer for all
inter-bot communication. The Nexus Bus (`src/nexus/bus/`) provides:

1. `NexusEvent` dataclass with 20 typed event types
2. JSON serializer/deserializer for all event payloads
3. `ConsumerManager` with consumer groups and dead-letter routing
4. `NexusBus` async client with publish/subscribe, automatic reconnection,
   and stream trimming

Bots publish events to Redis Streams instead of sending Discord messages.
Other bots subscribe via consumer groups and process events asynchronously.

## Rationale

- **Durable**: Redis Streams persist events until explicitly trimmed, so
  disconnected bots can replay missed events on reconnection.
- **Ordered**: Streams maintain insertion order per stream, eliminating the
  race conditions that plagued Discord channel communication.
- **Consumer groups**: Redis consumer groups provide at-least-once delivery
  with automatic pending-entry tracking, ensuring no event is lost if a bot
  crashes mid-processing.
- **Dead-letter routing**: Events that fail processing after configurable
  retries are moved to a dead-letter stream for diagnosis.
- **No rate limits**: Redis has no Discord-style rate limits; the bus can
  handle thousands of events per second.
- **Decoupled from Discord**: Inter-bot communication no longer depends on
  the Discord gateway being connected, improving fleet resilience.

## Alternatives Considered

1. **Discord channels (existing)** — Rate-limited, non-durable, message
   ordering not guaranteed, cluttered user-facing channels.
2. **RabbitMQ** — More complex to deploy and operate; Redis is already
   running on Schubert for other purposes (session caching, memory).
3. **Kafka** — Designed for high-throughput streaming workloads; overkill
   for a fleet of 8 bots and adds significant operational complexity.

## Consequences

- Redis must be running for the fleet to coordinate. If Redis is down,
  bots fall back to standalone operation but cannot delegate or receive
  tasks.
- Bots must handle asynchronous event processing, which requires careful
  lifecycle management (subscribe on startup, unsubscribe on shutdown).
- Dead-letter streams require periodic monitoring and manual intervention
  for permanently failed events.

## References

- NX-SPEC-02: Nexus Bus (Redis Streams Event Transport)
- Redis Streams documentation: https://redis.io/docs/data-types/streams/
- Implementation: `src/nexus/bus/`
