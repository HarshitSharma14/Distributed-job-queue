# Distributed Job Queue — Implementation Tracker

This is the working checklist for implementation. We complete and verify each item before moving to the next.

## Current focus

- **Current phase:** Phase 6 — Reliability
- **Next step:** Implement the recovery monitor for expired `RUNNING` job leases
- **Current milestone:** Failed jobs use durable exponential backoff with jitter, and the scheduler safely releases due retries through the transactional outbox; 95 tests pass

## Phase 1 — Project foundation

- [x] Create the application package structure
- [x] Add configuration management
- [x] Add dependency management
- [ ] Add logging and shared error handling
- [x] Add the initial test structure

## Phase 1.5 — Local infrastructure

- [x] Create deployment-friendly Docker Compose configuration
- [x] Start PostgreSQL, Redis, and MinIO locally
- [x] Verify PostgreSQL health and connectivity
- [x] Verify Redis health and connectivity
- [x] Verify MinIO health and connectivity
- [x] Create and verify the MinIO result bucket
- [x] Document local service commands and required environment variables

## Phase 2 — Job domain and persistence

- [x] Define job statuses and valid state transitions
- [x] Define job, worker, and attempt models
- [x] Create PostgreSQL migrations
- [x] Implement job repository methods
- [x] Test state transitions and invalid updates

## Phase 3 — Queue primitives

- [x] Implement job enqueueing
- [x] Implement named queues
- [x] Implement priority ordering
- [x] Implement atomic job claiming
- [x] Implement job leases
- [x] Implement lease renewal
- [x] Implement requeue after lease expiry
- [x] Add transactional outbox for Redis publication
- [x] Implement the outbox publisher
- [x] Add unique lease fencing tokens
- [x] Add temporary Redis in-flight claims
- [x] Add PostgreSQL QUEUED-job reconciliation
- [x] Test concurrent claims and duplicate-claim prevention

## Phase 4 — Worker execution

- [x] Implement worker registration
- [x] Implement worker heartbeats
- [x] Implement long polling
- [x] Implement job handler registration
- [x] Implement successful job completion
- [x] Implement job failure reporting
- [x] Verify the complete worker execution flow

## Phase 5 — API service

- [x] Implement `POST /jobs`
- [x] Implement `GET /jobs/{job_id}`
- [x] Implement worker registration and heartbeat endpoints
- [x] Add the Worker Gateway module and limited worker-token dependency
- [x] Move job claim and start handoff behind the Worker Gateway
- [x] Move lease renewal behind the Worker Gateway
- [x] Implement job completion and failure endpoints
- [x] Remove direct PostgreSQL and Redis access from the worker runtime
- [x] Add request validation and idempotency handling
- [x] Add API tests

## Deferred — Worker security design

- [ ] Define worker credential issuance, expiration, rotation, and revocation
- [ ] Define publisher, producer, worker, and admin authorization scopes
- [ ] Define handler approval, signing, versioning, and artifact validation
- [ ] Return temporary signed URLs for required handler artifacts
- [ ] Define handler isolation and sandboxing requirements

## Phase 6 — Reliability

- [x] Implement exponential backoff with jitter
- [x] Implement the `RETRY_WAIT` state transition
- [x] Implement the scheduler
- [ ] Implement the recovery monitor
- [ ] Implement dead-letter handling
- [ ] Test worker crashes and expired leases
- [ ] Test retry exhaustion

## Phase 7 — Results and operations

- [ ] Add MinIO result storage
- [x] Store result references in PostgreSQL
- [ ] Add structured logs
- [ ] Add queue, worker, retry, and failure metrics
- [ ] Add job and worker status views

## Phase 8 — Running the system

- [ ] Add Dockerfiles
- [ ] Add Docker Compose services
- [ ] Run API, workers, scheduler, recovery, PostgreSQL, Redis, and MinIO together
- [ ] Document local setup and commands
- [ ] Run the complete integration test suite

## Definition of done

- [ ] Submit a job from a client
- [ ] Store and track its lifecycle
- [ ] Process it with a worker
- [ ] Store its result
- [ ] Retry a failed job with backoff
- [ ] Recover a job after a worker crash
- [ ] Move permanently failed jobs to the dead-letter queue
- [ ] Run the full system with Docker Compose

## Progress notes

| Date | Completed | Notes |
|---|---|---|
| 2026-08-17 | Design documents created | HLD, component design, LLD, and technology decisions are documented |
| 2026-08-17 | Repository structure created | Added `src/`, application packages, test directories, migrations directory, and `pyproject.toml` |
| 2026-08-17 | Configuration management added | Added environment-based settings, validation, tests, and `.env.example` |
| 2026-08-20 | Local infrastructure completed | PostgreSQL, Redis, and MinIO started, verified, and documented |
| 2026-08-20 | Job state machine added | Added statuses, allowed transitions, validation, and unit tests |
| 2026-08-20 | Persistence models added | Added SQLAlchemy models for jobs, workers, and attempts |
| 2026-08-20 | Dependencies installed | Installed the project package, SQLAlchemy, psycopg, and pytest in the virtual environment |
| 2026-08-20 | Initial migration added | Added Alembic configuration and schema migration for jobs, workers, and attempts |
| 2026-08-23 | Initial migration applied | Successfully created the PostgreSQL schema with `alembic upgrade head` |
| 2026-08-23 | Job repository added | Added SQLAlchemy session setup and repository operations for jobs and attempts |
| 2026-08-23 | Repository integration tests added | Verified PostgreSQL persistence, lifecycle transitions, invalid updates, and attempt history |
| 2026-08-23 | Redis enqueueing added | Added named Redis sorted-set queues with priority ordering and integration tests |
| 2026-08-26 | Redis claiming verified | Fixed Lua argument mapping and verified priority claims, lease ownership, and renewal; full suite passes with 15 tests |
| 2026-08-26 | Recovery architecture corrected | Moved authoritative recovery to PostgreSQL, added fencing tokens and transactional outbox, and reduced Redis to temporary coordination state |
| 2026-08-26 | Durable recovery verified | Applied migration `0002`, confirmed no Alembic drift, and passed all 17 tests |
| 2026-08-26 | Claim handoff corrected | Added idempotent enqueueing, ready-to-in-flight claims, timeout return, claim abandonment, and PostgreSQL queue reconciliation |
| 2026-08-26 | Outbox publisher added | Added locked batch publication, idempotent Redis delivery, job state transition, process runner, and rollback/retry coverage |
| 2026-08-25 | Redis claiming and leases added | Added atomic Lua-script claims, worker leases, lease renewal, and integration tests |
| 2026-08-27 | Worker presence added | Added worker registration/reconnection, capabilities, periodic heartbeats, graceful offline marking, stale-worker monitoring, and PostgreSQL integration tests |
| 2026-08-27 | Worker claim handoff added | Added Redis blocking notifications, prioritized atomic claims, handler registration, stale-claim cleanup, and fenced Redis-to-PostgreSQL `RUNNING` handoff |
| 2026-08-27 | Fenced handler execution added | Added attempt-at-start accounting, background Redis/PostgreSQL lease renewal, token-guarded completion/failure, retry-wait selection, and lease-loss rejection |
| 2026-08-28 | Worker runtime completed | Added explicit handler-module loading, independent heartbeats, queue subscription rotation, blocking claim/execution loop, graceful shutdown, and end-to-end runtime coverage |
| 2026-08-28 | Job submission API added | Added validated `POST /jobs`, request-scoped transactions, atomic job/outbox persistence, deployable API runner, and HTTP integration tests |
| 2026-08-28 | Job detail API added | Added UUID-validated lookup, authoritative lifecycle fields, ordered attempt history, internal-token filtering, and not-found coverage |
| 2026-08-28 | Submission idempotency added | Added durable idempotency keys, canonical request fingerprints, conflict detection, replay headers, a unique database constraint, and concurrent-race coverage |
| 2026-08-28 | Worker trust boundary locked | Workers become execution agents behind a Worker Gateway and receive no PostgreSQL, Redis, or permanent storage credentials; detailed security design is deferred |
| 2026-08-28 | Worker Gateway presence API added | Added temporary bearer-token protection, worker registration, heartbeat, validation, persistence integration, environment configuration, and API coverage; all 68 tests pass |
| 2026-08-28 | Worker Gateway claim API added | Moved Redis long polling, atomic claims, capability validation, PostgreSQL `RUNNING` handoff, attempt creation, and stale/incompatible claim cleanup behind the gateway; all 72 tests pass |
| 2026-08-28 | Worker Gateway lease renewal added | Added token-fenced renewal across authoritative PostgreSQL state and temporary Redis coordination, with stale-token and missing-lease rejection; all 76 tests pass |
| 2026-08-28 | Worker Gateway finalization added | Added migration `0004`, durable attempt fencing tokens, idempotent completion/failure replay, result references, retry/terminal failure selection, and best-effort Redis cleanup; all 81 tests pass |
| 2026-08-28 | Worker runtime isolated from infrastructure | Added the HTTP Gateway client and refactored registration, heartbeat, claim, renewal, completion, and failure so worker code imports neither Redis nor PostgreSQL; all 85 tests pass |
| 2026-08-28 | Durable retry scheduling added | Added capped exponential backoff with jitter, persisted retry availability, concurrent-safe scheduler batches, transactional outbox release, process configuration, and retry integration tests; all 95 tests pass |
