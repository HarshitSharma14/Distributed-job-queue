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

FastAPI application and process runner. Authentication routes expose human sessions and Producer API keys. Job Type routes own Publisher definitions, immutable successor creation, bundle verification, and Admin-only signed approval or rejection. `publisher_routes.py` and `producer_routes.py` expose role-specific dashboard boundaries; `dashboard_services.py` and `dashboard_schemas.py` provide their shared pagination and analytics contracts. Worker management routes issue one-time enrollments and list or revoke owned agents, while `worker_dashboard_routes.py` and its matching service/schema modules expose owned assignments and attempt history. `admin_routes.py`, `admin_services.py`, and `admin_schemas.py` expose global safe job, analytics, Worker, queue, and dead-letter views. `dependencies.py` authenticates registrations and per-agent requests without holding a database connection during long polling. Worker Gateway routes expose registration, heartbeat, claim, renewal, result upload, completion, and failure. Services own state changes; routes own HTTP validation and authorization boundaries.

### `auth/`

Human, Producer, and Worker authentication primitives. Passwords use Argon2id. Opaque session, CSRF, Producer API, Worker enrollment, and Worker Agent tokens are generated cryptographically; PostgreSQL stores only hashes. Enrollments are short-lived and single-use. Agent credentials expire, rotate on re-enrollment, can be revoked, and are bound to one owner, Worker ID, Job Type, and queue. `handler_signing.py` defines canonical Ed25519 release signing and verification; `signing_cli.py` generates platform key pairs.

### `domain/`

Core concepts and rules: job entities, statuses, state transitions, user roles, job-type status, worker capabilities, and capped exponential retry timing with jitter. This package remains independent of HTTP, Redis, and database details.

### `persistence/`

SQLAlchemy models, database sessions, migrations, and repositories for users, roles, browser sessions, Producer credentials, Worker enrollments and credentials, versioned Job Types with linear predecessor links, handler approval audits and signatures, jobs, attempts, workers, results, and dead letters. `dashboard.py` owns scoped and global job lists and aggregates, `worker_dashboard.py` owns agent-ownership joins, and `admin_dashboard.py` owns global Worker and queue summaries. Job rows retain immutable ownership snapshots. Worker credentials link an owned agent to the exact enrolled Job Type. Producer idempotency and Publisher ownership are enforced by PostgreSQL.

### `queueing/`

Redis queue operations: sorted-set priority ordering, blocking-list wake-up notifications, atomic claims, leases, renewal, and requeue. Redis-specific behavior stays behind clear interfaces.

### `publisher/`

Transactional outbox publishing. Reads locked PostgreSQL outbox events, idempotently publishes job IDs to Redis, transitions jobs to `QUEUED`, and marks events published.

### `workers/`

Worker execution-agent lifecycle with no infrastructure access. `gateway_client.py` implements authenticated control calls and bounded credential-free downloads. `bundles.py` revalidates and temporarily installs bundles without importing them. `sandbox.py` registers execution proxies and enforces ephemeral Docker isolation; `sandbox_entrypoint.py` is the minimal JSON protocol inside the container. `consumer.py` claims work, while `executor.py` renews leases and reports outcomes. Trusted local modules may run in-process; downloaded Publisher code never does. No Worker module imports Redis, SQLAlchemy, repositories, or platform session factories.

### `scheduler/`

Releases durable retries when their PostgreSQL `available_at` time arrives. It locks due `RETRY_WAIT` rows with `SKIP LOCKED`, changes them to `QUEUED`, and creates transactional outbox events. The separate publisher performs Redis delivery.

### `storage/`

Private object-storage adapters. The result adapter creates short-lived, attempt-scoped signed uploads. The handler adapter reserves isolated upload keys, verifies bundle integrity and safe ZIP structure, and promotes accepted bytes to content-addressed keys that were never writable through signed upload URLs. Permanent MinIO credentials remain inside the API process, while PostgreSQL stores opaque object references and verification metadata.

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
