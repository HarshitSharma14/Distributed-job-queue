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

PostgreSQL also enforces immutable Job Type release history with unique `(publisher_id, name, version)` values and a unique self-referencing `supersedes_job_type_id`. The API locks the latest family row before creating the next draft, while database constraints reject concurrent branches.

Publisher dashboard totals are computed directly in PostgreSQL under a mandatory `publisher_id` predicate. Composite Publisher/time and Publisher/status indexes support keyset pagination, filters, and grouped lifecycle counts. Prometheus remains reserved for operational trends and is never queried directly by a browser.

Producer dashboard queries reuse the same service and repository contracts under a mandatory `producer_id` predicate. Matching Producer/time and Producer/status indexes support its list and aggregate paths. Browser sessions and scoped opaque API keys share authorization logic, but raw keys remain hash-only and revocable.

Worker dashboard queries join jobs and attempts through `workers.owner_user_id`. Composite Worker/status and Worker/attempt-time indexes support active assignments and cursor-paginated history. Active assignment order uses the current attempt's immutable start time rather than lease-renewal timestamps.

Admin dashboard reads reuse PostgreSQL aggregate and keyset-pagination services without an ownership restriction only after an Admin browser session is verified. Global status/time, queue/status, and Worker status/time indexes support operational lists. Queue views merge PostgreSQL aggregates with Redis ready and in-flight cardinalities while keeping both sources clearly labeled.

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

### Choose: Redis sorted sets, blocking lists, and atomic Lua scripts

Sorted sets provide priority ordering. Per-queue blocking lists act only as worker wake-up channels, allowing `BRPOP` to hold idle connections without repeated polling. Lua scripts atomically enqueue with a notification, claim jobs, and create short-lived tokenized leases. Durable job state and recovery remain in PostgreSQL.

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

Workers communicate exclusively with a Worker Gateway API. The gateway owns PostgreSQL, Redis, and object-storage access and performs long polling, claims, lease changes, and state transitions on the worker's behalf. Workers receive only job-specific payloads, approved handler information, fenced lease tokens, and temporary signed artifact URLs.

Python workers use a synchronous `httpx` client because handler execution is currently synchronous. Heartbeats and lease renewal run in independent threads through the same HTTP abstraction.

Registration accepts a short-lived, one-time opaque enrollment token created by an authenticated Worker user. The gateway exchanges it for an expiring, revocable opaque credential bound to one Worker Agent and stores only its SHA-256 hash. Every later operation verifies the bound Worker ID, exact Job Type ID, and assigned queue. Re-enrollment rotates the credential; dashboard revocation takes effect immediately.

The agent credential can request a short-lived signed GET URL only for its assigned immutable handler. The Worker downloads without permanent credentials, enforces limits, verifies SHA-256, and rechecks the ZIP manifest. Executing downloaded code requires an explicit runtime flag and uses a fresh restricted Docker container per attempt. The agent process never imports Publisher code.

The URL signature controls temporary storage access; it is not the release signature. Publisher verification places the immutable bundle in `PENDING_APPROVAL`. An Admin signs the exact Job Type ID, name, version, and SHA-256 digest with Ed25519 before activation. The API alone receives the private key. Workers receive a map of trusted public keys and reject unknown key IDs, altered metadata, or invalid signatures before installation. The `cryptography` package provides Ed25519 primitives, and key IDs support rotation.

The sandbox uses a digest-pinned Python image, no network, read-only root and handler filesystems, a non-root user, dropped capabilities, `no-new-privileges`, default seccomp, and CPU, memory/swap, PID, file-descriptor, timeout, and output limits. JSON over stdin/stdout is the only execution protocol. Docker is the practical free/local choice; stronger hostile multi-tenant deployments should evaluate gVisor or microVM isolation.

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

PostgreSQL stores an opaque `result_reference`; MinIO stores the output in a private bucket. The Worker Gateway validates the active lease and issues a short-lived, attempt-scoped signed PUT URL. Workers upload through that URL and never receive permanent MinIO credentials.

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
Queue:               Redis sorted sets + blocking notification lists
Queue Atomicity:     Redis Lua scripts
Workers:             Python processes
Job Delivery:        Gateway HTTP long poll + internal Redis atomic claim
Control Communication: Worker Gateway REST API
Worker HTTP Client:   httpx
Worker Infrastructure Access: None
Result Storage:      MinIO
Handler Storage:     Private MinIO bucket with signed uploads and immutable promotion
Handler Approval:    Admin-controlled release activation
Release Signing:     Ed25519 via cryptography; API private key + Worker trusted public keys
Deployment:          Docker Compose
Testing:             Pytest
Logging:             Python logging with redacted JSON output
API Errors:          Stable coded JSON envelope with request IDs
Metrics Client:      Prometheus Python client
Metrics Storage:     Grafana Cloud Free or local Prometheus
Dashboard Analytics: PostgreSQL exact data + Prometheus operational trends
Password Hashing:    Argon2id via argon2-cffi
Browser Auth:        Opaque PostgreSQL sessions + secure cookies + CSRF tokens
Producer Auth:       Hashed, scoped, expiring, revocable opaque API keys
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
                       │       │
                       └───┬───┘
                           ▼
                    Worker Gateway
                           │ HTTPS
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
