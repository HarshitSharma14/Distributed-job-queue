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

FastAPI application and process runner. `schemas.py` defines public and worker-gateway contracts, while `dependencies.py` owns request-scoped transactions, internal Redis construction, and the temporary worker-token boundary. `services.py` coordinates producer-facing job operations. `worker_gateway_services.py` owns worker presence, the Redis-to-PostgreSQL claim handoff, and fenced lease renewal. `routes.py` exposes producer-facing HTTP operations; `worker_gateway_routes.py` exposes registration, heartbeat, claim, and lease endpoints and will also own completion and failure reporting. Business rules do not belong in route handlers.

### `domain/`

Core concepts and rules: job entities, statuses, state transitions, retry policy, and worker capabilities. This package should remain independent of HTTP, Redis, and database details.

### `persistence/`

SQLAlchemy models, database sessions, migrations integration, and repositories for jobs, attempts, workers, and results.

### `queueing/`

Redis queue operations: sorted-set priority ordering, blocking-list wake-up notifications, atomic claims, leases, renewal, and requeue. Redis-specific behavior stays behind clear interfaces.

### `publisher/`

Transactional outbox publishing. Reads locked PostgreSQL outbox events, idempotently publishes job IDs to Redis, transitions jobs to `QUEUED`, and marks events published.

### `workers/`

Worker execution-agent lifecycle. `handlers.py` loads explicit handler modules and maps durable job types to functions, while `runner.py` owns the process loop, error isolation, and graceful shutdown. The current `runtime.py`, `consumer.py`, and infrastructure-aware portions of `executor.py` are transitional: registration, heartbeat, claim, and renewal now have gateway equivalents; completion and failure finalization still need to move behind the Worker Gateway before the final worker can drop PostgreSQL and Redis access.

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
API/Gateway ───────┐
Workers ──HTTP─────┤
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
