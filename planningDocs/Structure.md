# Distributed Job Queue — Codebase Structure

This document explains where code belongs and helps us navigate the project as it grows.

## Current structure

```text
distributed_job_queue/
├── planningDocs/
│   ├── HLD+Component_Design+LLD.md
│   ├── Implementation_Tracker.md
│   ├── Technology_Design.md
│   ├── Structure.md
│   ├── marketResearch.md
│   └── roughPlan.md
├── src/
│   └── distributed_job_queue/
│       ├── api/
│       ├── auth/
│       ├── common/
│       ├── domain/
│       ├── persistence/
│       ├── publisher/
│       ├── queueing/
│       ├── recovery/
│       ├── scheduler/
│       ├── storage/
│       └── workers/
├── tests/
│   ├── unit/
│   └── integration/
├── migrations/
├── pyproject.toml
└── README.md              # Add when local setup is documented
```

## Package responsibilities

### `src/distributed_job_queue/`

Main application package. Production code lives here.

### `api/`

FastAPI application and process runner. Authentication routes expose login, logout, and current-user identity, while authentication dependencies resolve revocable browser sessions and enforce CSRF protection. `schemas.py` defines public and worker-gateway contracts, while `dependencies.py` owns request-scoped transactions, internal Redis construction, and the temporary worker-token boundary. `services.py` coordinates producer-facing job operations. `worker_gateway_services.py` owns worker presence, claim handoff, lease renewal, and idempotent terminal reporting. `routes.py` exposes producer-facing HTTP operations; `worker_gateway_routes.py` exposes the complete worker control protocol: registration, heartbeat, claim, renewal, completion, and failure. Business rules do not belong in route handlers.

### `auth/`

Human authentication primitives and services. Passwords use Argon2id, opaque session and CSRF tokens are generated cryptographically, and only token hashes are persisted. The CLI creates initial users without placing passwords in shell history.

### `domain/`

Core concepts and rules: job entities, statuses, state transitions, user roles, job-type status, worker capabilities, and capped exponential retry timing with jitter. This package remains independent of HTTP, Redis, and database details.

### `persistence/`

SQLAlchemy models, database sessions, migrations integration, and repositories for users, role assignments, versioned job types, jobs, attempts, workers, results, and durable dead-letter records. Job rows retain immutable `job_type_id`, `publisher_id`, and `producer_id` ownership snapshots, while each Worker Agent references its owning user. Producer-scoped idempotency and the Job Type-to-Publisher relationship are enforced by PostgreSQL.

### `queueing/`

Redis queue operations: sorted-set priority ordering, blocking-list wake-up notifications, atomic claims, leases, renewal, and requeue. Redis-specific behavior stays behind clear interfaces.

### `publisher/`

Transactional outbox publishing. Reads locked PostgreSQL outbox events, idempotently publishes job IDs to Redis, transitions jobs to `QUEUED`, and marks events published.

### `workers/`

Worker execution-agent lifecycle with no infrastructure access. `gateway_client.py` implements the authenticated HTTP control protocol. `consumer.py` claims assignments through that client and attaches locally installed handlers. `executor.py` runs handlers, renews leases in a background thread, and reports terminal outcomes through the gateway. `runtime.py` creates process identities, and `runner.py` combines registration, heartbeats, queue rotation, execution, error isolation, and graceful shutdown. No module in this package imports Redis, SQLAlchemy, repositories, or platform session factories.

### `scheduler/`

Releases durable retries when their PostgreSQL `available_at` time arrives. It locks due `RETRY_WAIT` rows with `SKIP LOCKED`, changes them to `QUEUED`, and creates transactional outbox events. The separate publisher performs Redis delivery.

### `storage/`

Private object-storage adapters. The MinIO adapter creates short-lived, attempt-scoped signed uploads while permanent access credentials remain inside the API process. PostgreSQL stores only the resulting opaque object key.

### `recovery/`

PostgreSQL-authoritative health and recovery process. It marks workers offline after their heartbeat deadline, locks expired `RUNNING` jobs, fails and fences their active attempts, clears ownership, moves recoverable jobs to `RETRY_WAIT`, and dead-letters exhausted jobs.

### `common/`

Shared configuration, structured logging, and operational metrics. `logging.py` owns JSON formatting, request context, process configuration, and sensitive-value redaction. `metrics.py` owns low-cardinality counters, histograms, current-state collectors, and private process metric servers. API-specific errors, HTTP correlation, and protected scraping remain under `api/`.

## Test structure

### `tests/unit/`

Fast tests for domain rules, retry calculations, state transitions, and isolated queue/persistence behavior using fakes or mocks.

### `tests/integration/`

Tests involving real PostgreSQL, Redis, MinIO, or multiple running components. These verify claims, leases, retries, and recovery across process boundaries.

## Supporting directories

### `migrations/`

Versioned database schema changes. Every model change that affects PostgreSQL should have a migration.

### `planningDocs/`

Architecture decisions, research, implementation tracking, and navigation documentation. Update the relevant design document when a locked decision changes.

## Dependency direction

```text
Workers ──HTTP──> API/Gateway ───┐
Scheduler ───────────────────────┼──> Application/domain rules
Recovery ────────────────────────┤             │
Publisher ───────────────────────┘             │
                                              ├──> Persistence interfaces
                                              └──> Queue interfaces

Persistence ──> PostgreSQL adapter
Queueing ──────> Redis adapter
```

The domain layer should not import API frameworks or infrastructure clients. Infrastructure details should be replaceable behind interfaces where that improves testing or clarity.

## Navigation rule

When adding a feature, start with the domain behavior, then add the required adapter or process integration, and finally add unit and integration tests in the matching test directory.
