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
│       ├── common/
│       ├── domain/
│       ├── persistence/
│       ├── publisher/
│       ├── queueing/
│       ├── recovery/
│       ├── scheduler/
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

HTTP routes, request/response schemas, and API dependencies. This layer translates HTTP requests into application operations; business rules do not belong in route handlers.

### `domain/`

Core concepts and rules: job entities, statuses, state transitions, retry policy, and worker capabilities. This package should remain independent of HTTP, Redis, and database details.

### `persistence/`

SQLAlchemy models, database sessions, migrations integration, and repositories for jobs, attempts, workers, and results.

### `queueing/`

Redis queue operations: sorted-set priority ordering, blocking-list wake-up notifications, atomic claims, leases, renewal, and requeue. Redis-specific behavior stays behind clear interfaces.

### `publisher/`

Transactional outbox publishing. Reads locked PostgreSQL outbox events, idempotently publishes job IDs to Redis, transitions jobs to `QUEUED`, and marks events published.

### `workers/`

Worker process lifecycle. `runtime.py` owns registration and heartbeat operations, `handlers.py` maps durable job types to executable functions, and `consumer.py` performs the Redis-to-PostgreSQL claim handoff. `runner.py` owns process signals and graceful shutdown. Handler execution, lease renewal, and completion/failure reporting are the next layer.

### `scheduler/`

Finds delayed and retryable jobs that are ready, then publishes them to the appropriate queue.

### `recovery/`

Health and recovery processes. Its current runner marks workers offline after their heartbeat deadline. Job lease recovery and retry exhaustion handling will also live here.

### `common/`

Shared configuration, logging, errors, time utilities, IDs, and cross-cutting helpers. Keep this package small to avoid turning it into a catch-all.

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
API ───────────────┐
Workers ───────────┤
Scheduler ─────────┼──> Application/domain rules
Recovery ──────────┘             │
Publisher ─────────┤             │
                                 ├──> Persistence interfaces
                                 └──> Queue interfaces

Persistence ──> PostgreSQL adapter
Queueing ──────> Redis adapter
```

The domain layer should not import API frameworks or infrastructure clients. Infrastructure details should be replaceable behind interfaces where that improves testing or clarity.

## Navigation rule

When adding a feature, start with the domain behavior, then add the required adapter or process integration, and finally add unit and integration tests in the matching test directory.
