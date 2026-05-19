# ADR-0042: Event-sourced orders backend

- **Status:** Accepted
- **Date:** 2026-03-18
- **Deciders:** Platform team, Orders working group

## Context

The legacy `orders_v0` table stores the current state of every order as a row, updated in place by the API. This makes it cheap to query but expensive to audit: reconstructing the history of an order requires joining four audit tables and is unreliable for rows older than 90 days.

Three things have changed since `orders_v0` was designed:

1. Compliance now requires a full, immutable history of every state transition for at least seven years.
2. The fulfillment service has grown to depend on out-of-band reads from a debezium feed — fragile and high-latency.
3. We need to support concurrent updates from multiple regions without losing writes.

## Decision

Move to an **event-sourced** backend. The Orders API appends events to a per-order stream, and a projector builds materialized read models from those streams. Read models are denormalized for the common query shapes (by-customer, by-status, recent).

```
Write path:  API → append(event) → event store → projector → read model
Read path:   API → read model (with fallback to replay for cold orders)
```

## Consequences

**Positive**

- Full immutable history comes "for free" — every state transition is an event
- Fulfillment can subscribe to the event bus directly; no more debezium sidecar
- Multi-region writes are reconciled by the projector, not the DB

**Negative**

- Eventual consistency between write and read paths (target: <500ms p99)
- More moving parts to operate — see [runbooks/orders-fulfillment.md](../runbooks/orders-fulfillment.md)
- Replaying a hot order's stream during a read miss is slower than a single-row select

## Alternatives considered

- **Keep `orders_v0`, add CDC** — Cheaper to build but doesn't solve the audit-history problem and keeps the debezium dependency.
- **Move to a managed event-sourcing platform** — Evaluated EventStoreDB and AxonIQ. Both are good but introduce a vendor we'd be on the hook to operate; we chose to build on Kafka, which we already run.
