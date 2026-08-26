# Distributed Job Queue — Technology Design

This document decides which technologies implement the architecture defined in the HLD and LLD.

For each decision:

1. Present the major options
2. Compare pros and cons
3. Choose one option
4. Lock the decision

---

# 1. API Framework

The API submits jobs, queries status, registers workers, and exposes control endpoints.

## Option A: FastAPI

**Pros:** typed validation with Pydantic, async support, clean APIs, and fast development.

**Cons:** Python has lower raw performance than Go, and async code requires event-loop knowledge.

## Option B: Flask

**Pros:** simple, mature, and easy to understand.

**Cons:** more manual setup and weaker async support.

## Option C: Go with Gin or Fiber

**Pros:** excellent concurrency and performance; common in infrastructure software.

**Cons:** more code and slower iteration for this project.

## Decision

### Choose: FastAPI

The learning goal is distributed systems, not framework performance. FastAPI provides clean contracts, type safety, and quick iteration.

---

# 2. Primary Database

The database stores jobs, workers, attempts, and execution history.

## Option A: PostgreSQL

**Pros:** strong transactions, row locking, JSON support, and powerful queries.

**Cons:** requires deliberate schema design.

## Option B: MySQL

**Pros:** mature, reliable, and widely used.

**Cons:** slightly less convenient for complex JSON data and this state-heavy design.

## Option C: MongoDB

**Pros:** flexible documents and easy schema changes.

**Cons:** weaker fit for transactional job state and strict consistency guarantees.

## Decision

### Choose: PostgreSQL

Job claiming, state changes, and attempt creation require correctness and transactions.

---

# 3. Queue Technology

The queue stores ready jobs, supports priority ordering, claims, and leases.

## Option A: Redis

**Pros:** fast atomic operations, sorted sets for priorities, blocking operations, and easy local deployment.

**Cons:** not a full message broker; persistence requires configuration.

## Option B: RabbitMQ

**Pros:** purpose-built messaging, acknowledgements, routing, and dead lettering.

**Cons:** more operational complexity; job state still needs separate handling.

## Option C: PostgreSQL queue

**Pros:** simple and strongly consistent.

**Cons:** database contention and less realistic queue behavior at higher throughput.

## Decision

### Choose: Redis sorted sets with atomic Lua scripts

This provides priority queues and short-lived tokenized leases while keeping durable job state and recovery in PostgreSQL.

---

# 4. Database Access

## Option A: SQLAlchemy

**Pros:** explicit models, transaction control, and strong PostgreSQL support.

**Cons:** more setup than a framework-integrated ORM.

## Option B: Django ORM

**Pros:** mature and convenient.

**Cons:** couples the project to Django, which is not required for the API.

## Option C: Raw SQL

**Pros:** maximum control and direct SQL knowledge.

**Cons:** more boilerplate and harder maintenance.

## Decision

### Choose: SQLAlchemy

This is an infrastructure project, so explicit SQL and transaction boundaries are valuable.

---

# 5. Worker Language

Workers need queue communication, concurrency, heartbeats, and task execution.

## Option A: Python

**Pros:** same ecosystem as the API, fast development, and easy task integration.

**Cons:** weaker for CPU-heavy workloads because of the GIL.

## Option B: Go

**Pros:** excellent concurrency and realistic infrastructure experience.

**Cons:** introduces a second language and increases project complexity.

## Option C: Java

**Pros:** strong concurrency tools and broad enterprise adoption.

**Cons:** more verbose and unnecessary for this scope.

## Decision

### Choose: Python workers

One language keeps the focus on distributed-systems behavior instead of language boundaries.

---

# 6. Worker Communication

Workers need registration, heartbeats, completion, and failure reporting.

## Option A: REST over HTTP

**Pros:** simple, debuggable, and easy to test.

**Cons:** more overhead than a binary protocol.

## Option B: gRPC

**Pros:** fast, strongly typed, and supports streaming.

**Cons:** more setup and operational complexity.

## Option C: WebSockets

**Pros:** real-time bidirectional communication.

**Cons:** connection lifecycle and reconnect behavior are more complex.

## Decision

### Choose: REST over HTTP

Redis handles asynchronous job delivery. Workers only need simple, inspectable control communication.

---

# 7. Result Storage

Results may be small JSON values, large files, or generated artifacts.

## Option A: PostgreSQL

**Pros:** simple and transactional.

**Cons:** unsuitable for large files and binary artifacts.

## Option B: Object storage

Examples include S3 and MinIO.

**Pros:** designed for files, durable, and scalable.

**Cons:** adds another component.

## Decision

### Choose: MinIO with an S3-compatible interface

PostgreSQL stores result metadata and a `result_reference`; MinIO stores large outputs. This keeps the design production-like while remaining easy to run locally.

---

# 8. Containerization

## Option A: Run directly on the host

**Pros:** simplest setup.

**Cons:** environment differences and manual service management.

## Option B: Docker Compose

**Pros:** reproducible environments and one command to run the complete system.

**Cons:** small containerization learning curve.

## Decision

### Choose: Docker Compose

The local stack contains:

```text
api
worker
scheduler
recovery
postgres
redis
minio
```

---

# 9. Testing

## Options

### Unit tests only

**Pros:** fast and simple.

**Cons:** misses queue, database, and failure interactions.

### Integration tests only

**Pros:** validates real components.

**Cons:** slower and harder to isolate failures.

### Unit plus integration tests

**Pros:** balances fast feedback with system-level confidence.

**Cons:** requires more test setup.

## Decision

### Choose: Pytest with unit, integration, and failure-recovery tests

Tests must cover state transitions, atomic claims, retries, expired leases, duplicate completion, and dead-letter handling.

---

# Final Technology Stack Locked

```text
API:                 FastAPI
Language:            Python
Database:            PostgreSQL
Database Access:     SQLAlchemy
Queue:               Redis sorted sets
Queue Atomicity:     Redis Lua scripts
Workers:             Python processes
Communication:       REST over HTTP
Result Storage:      MinIO
Deployment:          Docker Compose
Testing:             Pytest
```

## Final architecture with technologies

```text
                         Client
                           │
                           ▼
                     FastAPI API
                       │       │
                       ▼       ▼
                 PostgreSQL   Redis
                 Job state    Queues + temporary leases
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Worker 1      Worker 2      Worker 3
          Python        Python        Python
                           │
                           ▼
                         MinIO
                     Large results

             Outbox Publisher
               PostgreSQL → Redis

             Scheduler and Recovery
               PostgreSQL authority
```

This technology stack is now locked separately from the HLD, component design, and LLD.
