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

Redis queue operations: enqueue, priority ordering, atomic claim, leases, renewal, and requeue. Redis-specific behavior stays behind clear interfaces.

### `workers/`

Worker process lifecycle, registration, heartbeats, long polling, handler execution, completion, and failure reporting.

### `scheduler/`

Finds delayed and retryable jobs that are ready, then publishes them to the appropriate queue.

### `recovery/`

Detects expired leases and offline workers, safely requeues abandoned jobs, and handles retry exhaustion.

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
                                 ├──> Persistence interfaces
                                 └──> Queue interfaces

Persistence ──> PostgreSQL adapter
Queueing ──────> Redis adapter
```

The domain layer should not import API frameworks or infrastructure clients. Infrastructure details should be replaceable behind interfaces where that improves testing or clarity.

## Navigation rule

When adding a feature, start with the domain behavior, then add the required adapter or process integration, and finally add unit and integration tests in the matching test directory.
