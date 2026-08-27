# Distributed Job Queue — Implementation Tracker

This is the working checklist for implementation. We complete and verify each item before moving to the next.

## Current focus

- **Current phase:** Phase 5 — API service
- **Next step:** Implement `GET /jobs/{job_id}` with attempt history
- **Current milestone:** Transactional `POST /jobs` API implemented and verified; 50 tests pass

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
- [ ] Implement `GET /jobs/{job_id}`
- [ ] Implement worker registration and heartbeat endpoints
- [ ] Implement job completion and failure endpoints
- [ ] Add request validation and idempotency handling
- [ ] Add API tests

## Phase 6 — Reliability

- [ ] Implement exponential backoff with jitter
- [ ] Implement `RETRY_WAIT`
- [ ] Implement the scheduler
- [ ] Implement the recovery monitor
- [ ] Implement dead-letter handling
- [ ] Test worker crashes and expired leases
- [ ] Test retry exhaustion

## Phase 7 — Results and operations

- [ ] Add MinIO result storage
- [ ] Store result references in PostgreSQL
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
