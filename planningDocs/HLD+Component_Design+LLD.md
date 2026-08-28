# Distributed Job Queue — HLD, Component Design & LLD

This is the single design document for the Distributed Job Queue. It covers the HLD decisions, component responsibilities, low-level implementation details, and runtime behavior.

For every important implementation decision:

1. Explain the choice
2. Present the major options
3. Compare pros and cons
4. Choose one option
5. Move forward with that decision

---

# 1. How should the codebase be structured?

The system needs an API, workers, a scheduler, and shared infrastructure code.

## Option A: One process

Everything runs in one application.

### Advantages

- Simple to start and debug
- Fewer deployment concerns

### Disadvantages

- API and workers compete for resources
- One failure can affect the whole system
- Cannot scale components independently

## Option B: Separate processes with shared modules

Run the API, workers, scheduler, and recovery monitor as separate processes while sharing models and clients.

### Advantages

- Clear responsibilities
- Independent scaling and failure isolation

### Disadvantages

- More process and configuration management
- Requires clear service contracts

## Decision

### Choose: Separate API, worker, scheduler, and recovery processes

The codebase remains a modular monolith, but each runtime process has one responsibility. This gives us production-like boundaries without unnecessary microservices.

---

<!-- Technology choices are maintained separately.

# Technology choices

## Options

| Concern              | Options                              | Pros                                                                     | Cons                            |
| -------------------- | ------------------------------------ | ------------------------------------------------------------------------ | ------------------------------- |
| API                  | FastAPI, Flask, Django               | FastAPI gives typed contracts and async support                          | Adds framework conventions      |
| Job database         | PostgreSQL, Redis, document database | PostgreSQL is durable, transactional, and queryable                      | Requires a separate database    |
| Queue and leases     | Redis, RabbitMQ, PostgreSQL          | Redis provides atomic operations, blocking reads, priorities, and leases | Less specialized than RabbitMQ  |
| Data access          | SQLAlchemy, Django ORM, raw SQL      | SQLAlchemy gives explicit models and transactions                        | More setup than a framework ORM |
| Worker job delivery  | Redis blocking wait, polling, push   | Blocking waits avoid repeated empty requests while preserving worker pull | Requires a wake-up channel beside the priority sorted set |

## Decision

### Choose: FastAPI + PostgreSQL + Redis + SQLAlchemy + Redis blocking waits

PostgreSQL is the source of truth for job state. Redis handles ready queues and temporary leases. RabbitMQ, Kafka, and Temporal are not selected because they solve broader broker, event-streaming, and workflow problems than this task queue requires.

---

-->

# 2. What is the job data model?

The database must represent the job, its current state, every attempt, and the worker that owns it.

## Option A: Store only the current job row

### Advantages

- Simple schema
- Fewer database writes

### Disadvantages

- No attempt history
- Harder debugging and failure analysis

## Option B: Job row plus attempt records

### Advantages

- Complete execution history
- Easier retry analysis and monitoring

### Disadvantages

- More tables and writes

## Decision

### Choose: Job table plus worker and job-attempt tables

```text
jobs
----
id                 UUID primary key
type               string
queue              string
payload            JSON
priority           integer
status              enum
attempts           integer
max_attempts       integer
available_at       timestamp
lease_expires_at   timestamp nullable
lease_token        UUID nullable
worker_id          string nullable
result_ref         string nullable
error              JSON nullable
created_at         timestamp
updated_at         timestamp
completed_at       timestamp nullable
dead_lettered_at   timestamp nullable

workers
-------
id                 string primary key
capabilities       JSON
status             ONLINE | OFFLINE
last_heartbeat_at  timestamp
registered_at      timestamp

job_attempts
------------
id                 UUID primary key
job_id             UUID foreign key
worker_id          string
lease_token        UUID nullable, unique
attempt_number     integer
started_at         timestamp
finished_at        timestamp nullable
status             enum
error              JSON nullable
```

```text
outbox_events
-------------
id                 UUID primary key
job_id             UUID foreign key
event_type         string
payload            JSON
created_at         timestamp
published_at       timestamp nullable
```

Job creation and recovery write outbox events in the same PostgreSQL transaction. A publisher delivers pending events to Redis and marks them published.

Results are stored outside the job row; `result_ref` is an opaque, attempt-scoped object key. A worker with a live lease asks the Worker Gateway for a short-lived signed PUT URL, uploads without storage credentials, and then completes the job with that exact reference. The gateway rejects references belonging to another job or attempt.

---

# 3. How should the queue be represented internally?

We must decide how to implement that behavior of multiple queues with priority support.

## Option A: Redis list per queue

### Advantages

- Simple FIFO behavior
- Native blocking pop

### Disadvantages

- Priority requires multiple lists or custom logic
- Scheduling is less flexible

## Option B: Redis sorted set per queue

### Advantages

- Supports priority and ready-time ordering
- Atomic claim operations can be scripted

### Disadvantages

- Requires explicit blocking or polling behavior
- More implementation logic than lists

## Option C: RabbitMQ queues

### Advantages

- Purpose-built broker
- Native acknowledgements and routing

### Disadvantages

- More infrastructure and concepts
- Lease and job-state behavior still needs application logic

## Decision

### Choose: Redis sorted sets for named priority queues

Each job is routed to a validated queue such as `default`, `email`, or `image`. The score combines readiness and priority. Workers consume only queues matching their capabilities. Scheduling rules must prevent low-priority jobs from starving indefinitely.

---

# 4. What is the job state machine?

## Options

### Option A: Free-form status updates

Any component can change a job to any status.

- **Pro:** quick to implement
- **Con:** invalid states and race conditions are likely

### Option B: Explicit state machine

Only defined transitions are accepted.

- **Pro:** predictable behavior and safer concurrency
- **Con:** requires transition validation

## Decision

### Choose: Explicit state machine

```text
CREATED → QUEUED → RUNNING → COMPLETED
                         ├→ RETRY_WAIT → QUEUED
                         └→ DEAD_LETTERED
```

State meanings:

- `CREATED`: request accepted and being persisted.
- `QUEUED`: ready for a worker.
- `RUNNING`: claimed with an active lease.
- `RETRY_WAIT`: failed and waiting for its next attempt.
- `COMPLETED`: finished successfully.
- `FAILED`: an execution-attempt outcome retained in attempt history.
- `DEAD_LETTERED`: the job exhausted its retry limit and is retained for inspection.

Workers can complete or fail a job only while they own its active lease.

---

# 5. How is a job submitted and claimed?

## Submit flow

`POST /jobs`

```json
{
  "type": "generate_report",
  "queue": "default",
  "payload": { "user_id": 123 },
  "priority": 5,
  "max_attempts": 5,
  "available_at": "2026-08-16T09:00:00Z"
}
```

The API writes the `CREATED` job and a `JOB_READY` outbox event in one PostgreSQL transaction. An outbox publisher adds the job ID to Redis and changes it to `QUEUED`. An idempotency key prevents duplicate submissions.

## Claim options

### Option A: API assigns jobs

- **Pro:** central visibility
- **Con:** coordinator bottleneck and more failure responsibility

### Option B: Worker pulls jobs

- **Pro:** independent workers, natural horizontal scaling, easier recovery
- **Con:** requires leases, heartbeats, and recovery logic

## Decision

### Choose: Worker pull through a Worker Gateway API

1. The worker long-polls the Worker Gateway API for compatible work.
2. The gateway atomically claims a job in Redis and creates a temporary lease with a unique token.
3. The gateway conditionally changes PostgreSQL to `RUNNING`, storing the worker, token, and expiration.
4. The worker renews its lease through the gateway, which updates Redis and PostgreSQL.

If the worker crashes before step 3, the Redis in-flight deadline returns the job to ready. If Redis loses all temporary state, a reconciler creates outbox events for authoritative PostgreSQL `QUEUED` jobs.

The claim operation must be atomic so two workers cannot own the same queue entry.

---

# 6. How should workers communicate with the system?

## Options

### Option A: Short polling

- **Pro:** simple and reliable
- **Con:** creates unnecessary requests when the queue is empty

### Option B: Redis blocking wait

- **Pro:** Redis holds idle connections and wakes workers when work arrives
- **Con:** priority still requires a separate sorted set and atomic claim operation

### Option C: Streaming connection

- **Pro:** low latency and real-time communication
- **Con:** operationally complex; reconnect behavior must be carefully designed

## Decision

### Choose: HTTP long polling through a Worker Gateway API

Workers communicate only with the gateway using a limited worker token. The gateway performs the Redis blocking wait and atomic priority claim, then performs authoritative state changes in PostgreSQL. Workers never receive PostgreSQL, Redis, or object-storage credentials.

After assignment, a worker receives only the required job payload, approved handler metadata, a fenced lease token, and temporary signed artifact URLs when needed. It cannot query databases, modify queues, access unrelated jobs, or call internal services directly.

Detailed credential issuance, token rotation, handler approval, and execution sandboxing are intentionally deferred to a dedicated security design. This document locks only the trust boundary: the platform controls state and infrastructure; workers execute approved workloads.

## Worker endpoints

```text
POST /worker/v1/workers/register
POST /worker/v1/workers/{worker_id}/heartbeat
POST /worker/v1/jobs/claim
POST /worker/v1/jobs/{job_id}/lease/renew
POST /worker/v1/jobs/{job_id}/complete
POST /worker/v1/jobs/{job_id}/fail
GET  /jobs/{job_id}
```

---

# 7. How do we provide failure recovery?

## Worker failure options

| Option            | Pros                                   | Cons                                    |
| ----------------- | -------------------------------------- | --------------------------------------- |
| Timeout only      | Simple                                 | Slow and imprecise failure detection    |
| Heartbeat only    | Shows worker health                    | Does not by itself recover an owned job |
| Lease only        | Automatically releases work            | Does not show overall worker health     |
| Heartbeat + lease | Detects dead workers and recovers jobs | Requires two related mechanisms         |

## Decision

### Choose: Worker heartbeat plus job lease

Workers periodically update `last_heartbeat_at`. Redis holds a short-lived tokenized lease for coordination, while PostgreSQL stores authoritative ownership and expiration. Recovery locks expired `RUNNING` rows, fails and fences their active attempts, clears ownership, and moves recoverable jobs to `RETRY_WAIT`. The scheduler publishes them later through the transactional outbox after backoff.

This produces at-least-once delivery. Job handlers must therefore be idempotent.

## Job retry options

### Option A: Immediate retry

- **Pro:** simplest
- **Con:** can create retry storms during outages

### Option B: Fixed delay

- **Pro:** predictable
- **Con:** does not adapt to repeated failures

### Option C: Exponential backoff

- **Pro:** protects dependencies and spreads retry load
- **Con:** needs scheduling and maximum-delay rules

## Decision

### Choose: Exponential backoff with jitter and a dead-letter queue

```text
delay = min(base_delay × 2^(attempt - 1), max_delay) + jitter
```

After `max_attempts`, the job becomes `DEAD_LETTERED`; its payload, attempts, and errors remain available for inspection.

---

# 8. How should delayed jobs be scheduled?

## Options

### Option A: Workers check future jobs

- **Pro:** no extra process
- **Con:** couples scheduling to execution and wastes worker capacity

### Option B: Queue checks future jobs

- **Pro:** centralized timing behavior
- **Con:** mixes scheduling and delivery responsibilities

### Option C: Separate scheduler

- **Pro:** clear ownership and easier testing
- **Con:** adds another process to operate

## Decision

### Choose: Separate scheduler process

The scheduler finds `RETRY_WAIT` jobs where `available_at <= now`. In one PostgreSQL transaction, it locks a batch with `SKIP LOCKED`, changes each job to `QUEUED`, and creates an outbox event. The outbox publisher then delivers each job ID to Redis. This allows multiple schedulers to run safely and keeps PostgreSQL authoritative.

---

# 9. How should delivery guarantees be implemented?

## Options

### At-most-once

- **Pro:** no duplicate execution
- **Con:** a worker crash can permanently lose a job

### At-least-once

- **Pro:** jobs are recoverable after failures
- **Con:** duplicates are possible; handlers need idempotency

### Exactly-once

- **Pro:** ideal behavior in theory
- **Con:** extremely difficult across a database, queue, and worker; usually requires transactions and deduplication

## Decision

### Choose: At-least-once delivery

Reliability is more important than eliminating every duplicate. Completion, failure, and recovery use compare-and-set updates so only the current lease owner can change the job.

---

# 10. How do we protect consistency and concurrency?

## Options

### Option A: Trust each component

- **Pro:** less code
- **Con:** races can produce duplicate claims or invalid transitions

### Option B: Database locks only

- **Pro:** strong state consistency
- **Con:** Redis and database can disagree during queue operations

### Option C: Database transactions plus atomic Redis operations

- **Pro:** protects state transitions and queue claims at their respective boundaries
- **Con:** cross-system coordination still requires idempotent recovery

## Decision

### Choose: PostgreSQL transactions, transactional outbox, and Redis atomic commands/Lua scripts

- Use transactions for state changes and attempt records.
- Use row locks or compare-and-set updates for completion, failure, and recovery.
- Use a transactional outbox whenever PostgreSQL state must produce a Redis queue entry.
- Use atomic Redis operations for temporary claim, lease creation, renewal, and release.
- Use job IDs as deduplication keys.
- Use a unique lease token as a fencing token for renewal, completion, and failure.
- Treat worker completion after lease expiry as a safe, idempotent no-op or recovery race.

---

# 11. What should be observable?

## Options

### Minimal logs only

- **Pro:** fast to implement
- **Con:** difficult to diagnose distributed failures

### Logs, metrics, and status queries

- **Pro:** supports debugging, operations, and capacity planning
- **Con:** additional instrumentation work

## Decision

### Choose: Structured logs, metrics, and job/worker status endpoints

Logs are one JSON object per event. Relevant lifecycle events include `job_id`, `worker_id`, `queue`, `attempt_number`, `status`, and duration. HTTP requests receive an `X-Request-ID` that is returned to callers and propagated into logs. Authorization values, permanent credentials, lease tokens, signed URLs, and configured secrets are redacted.

API failures use one stable envelope:

```json
{
  "error": {
    "code": "WORKER_LEASE_LOST",
    "message": "Worker no longer owns this job",
    "request_id": "request-123"
  }
}
```

Track:

- queue depth and oldest queued job
- success, failure, retry, and dead-letter counts
- wait and processing time
- active and offline workers
- expired leases

Prometheus is used for operational trends, not exact publisher accounting. Metric labels remain bounded: queue, route template, status, outcome, and operation. They never contain job IDs, worker IDs, publisher IDs, lease tokens, or signed URLs. PostgreSQL remains the source for permission-scoped Publisher and Admin dashboard totals.

The API owns authoritative current-state gauges for jobs, workers, and Redis queue depth. Scheduler, recovery, and Outbox Publisher processes expose only their own counters on private metrics ports, preventing duplicate gauges when Prometheus scrapes multiple targets. The API `/metrics` endpoint requires a separate metrics token.

Terminology:

- **Publisher user:** authenticated product user who creates and owns job types and their approved handlers.
- **Producer:** authenticated product user who submits jobs using an existing job type.
- **Worker:** execution agent that can access only its assigned work through the Worker Gateway.
- **Admin:** platform operator with global visibility and management access.
- **Outbox Publisher:** internal process that transfers durable PostgreSQL events to Redis.

---

# 12. Who can see jobs and metrics?

## Options

### Separate role dashboards without ownership rules

- **Pro:** quick to build
- **Con:** authorization becomes inconsistent and can expose unrelated jobs

### Ownership-scoped views backed by one authorization model

- **Pro:** every query follows explicit, testable ownership relationships
- **Pro:** the same APIs can safely support Admin, Publisher, Producer, and Worker dashboards
- **Con:** requires identity, ownership, and authorization data in PostgreSQL

## Decision

### Choose: Ownership-scoped views backed by PostgreSQL

The access graph is:

```text
Publisher ──owns──> Job Type ──defines──> Jobs
Producer  ─submits──────────────────────> Job
Worker user ─owns──> Worker Agent ─executes──> Job Attempt
Admin     ─manages──────────────────────> Entire platform
```

Each job stores immutable `publisher_id`, `producer_id`, and `job_type_id` ownership references at submission. Each attempt stores its `worker_id`, and every registered Worker Agent stores its owning `owner_user_id`. Keeping an ownership snapshot on the job preserves historical authorization and auditability if a job type later changes ownership.

PostgreSQL enforces that the referenced Job Type belongs to the recorded Publisher and rejects changes to a job's three ownership fields after insertion. Idempotency keys are unique per Producer, so separate Producers may safely use the same client-generated key. Until Producer authentication is applied to job routes, those compatibility routes use an explicit bootstrap system user and legacy Job Type.

| Actor | Can see | Cannot see |
|---|---|---|
| Admin | All users, job types, jobs, payloads, results, attempts, workers, queues, dead letters, and platform metrics | Recover password hashes, previously issued token values, or permanent infrastructure secrets |
| Publisher | Owned job types; every job created from them; payloads, results, errors, attempts, relevant workers, and aggregated metrics for those job types | Other publishers' data, worker credentials, infrastructure credentials, or unrestricted raw Prometheus access |
| Producer | Every detail for jobs they submitted: request, lifecycle, result, errors, attempts, and job-scoped timings | Other producers' jobs, unrelated job-type analytics, worker credentials, or platform-wide controls |
| Worker | Its profile, active assignments, and its own attempt history, outcomes, errors, and timings | Other workers' history, unrelated jobs, direct PostgreSQL/Redis/storage access, or historical payload/result access by default |

“Everything” means all authorized product and operational details. It never includes passwords, credential hashes, bearer tokens, lease tokens, signed URLs, or PostgreSQL, Redis, and object-storage credentials. Sensitive values are redacted even for Admin; credentials can be revoked or rotated, not recovered.

Publisher and Producer totals come from PostgreSQL because they require exact ownership filtering. Prometheus remains a low-cardinality operational source. The Dashboard API combines these sources and applies authorization; browsers never query PostgreSQL, Redis, or Prometheus directly.

Worker payload access is temporary and assignment-scoped through the Worker Gateway. The dashboard shows safe job metadata and the worker's own execution record. Retaining payload or result access after execution requires an explicit job-type policy.

---

# 13. How do dashboard users authenticate?

## Options

### Self-contained JWT access tokens

- **Pro:** verification does not require a database lookup
- **Con:** immediate logout, revocation, and role changes require additional infrastructure

### Revocable server-side sessions

- **Pro:** logout, account disabling, and permission changes take effect immediately
- **Pro:** simple for a same-origin dashboard
- **Con:** each authenticated request reads session state

## Decision

### Choose: Revocable PostgreSQL-backed browser sessions

Users log in with email and password. Passwords are stored only as Argon2id hashes. Successful login creates independent cryptographically random session and CSRF tokens; PostgreSQL stores only their SHA-256 hashes.

The raw session token is sent in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie. State-changing dashboard requests must also send the CSRF token from its readable cookie in the `X-CSRF-Token` header. Logout revokes the database session and clears both cookies. Expired sessions, revoked sessions, disabled users, and invalid passwords are rejected with generic errors.

Browser sessions authenticate humans only. Producer API keys, Worker Agent credentials, the metrics token, and internal process credentials remain separate credential classes with narrower permissions.

---

# Runtime Flows

These flows describe the normal and failure paths the implementation must support.

## 1. Job submission flow

```text
Client
  │
  │ POST /jobs + optional Idempotency-Key
  ▼
API Service
  │
  ├─ Validate request
  └─ PostgreSQL transaction
       ├─ Create job as CREATED
       └─ Create JOB_READY outbox event
  │
  ▼
Return job_id and status=CREATED

Asynchronously:

Outbox publisher
  ├─ Publish job ID to Redis
  ├─ Mark event published
  └─ Change job state to QUEUED
```

The operation is safe to retry when the caller supplies an idempotency key. The API stores a canonical request fingerprint with a unique key: identical retries return the original job, while using the same key for different work returns a conflict.

## 2. Job execution flow

```text
Worker
  │
  │ Long-poll Worker Gateway API
  ▼
Gateway atomically claims job and creates tokenized Redis lease
  │
  ├─ Gateway updates PostgreSQL: QUEUED → RUNNING
  ├─ Store worker_id, lease_token, and lease_expires_at
  ├─ Create job-attempt record
  ├─ Worker renews lease through the gateway while processing
  ├─ Execute handler
  ├─ Request attempt-scoped signed result upload URL
  ├─ Upload result directly to MinIO without permanent credentials
  └─ Report the issued result_ref
       │
       ├─ Success: gateway saves result, marks COMPLETED, and removes lease
       └─ Failure: gateway records error and calculates retry or dead-letter
```

Only the worker holding the active lease may complete or fail the job. Each attempt retains its unique lease token after the job-level lease is cleared. This makes an identical completion or failure report safely replayable after a lost HTTP response while rejecting changed or stale terminal reports.

## 3. Failure recovery flow

```text
Worker starts job
  │
  ▼
Worker crashes or stops heartbeating
  │
  ▼
PostgreSQL lease_expires_at passes
  │
  ▼
Recovery monitor locks expired RUNNING row
  │
  ├─ Verify job is still RUNNING
  ├─ Finish the active attempt as FAILED
  ├─ Clear worker ownership
  ├─ If attempts remain: calculate backoff and mark RETRY_WAIT
  └─ If exhausted: mark the job FAILED
  │
  ▼
Outbox publisher requeues the job in Redis
  │
  ▼
Another worker claims and executes the job
```

The compare-and-set update prevents recovery from requeueing a job already completed by the original worker.

## 4. Retry flow

```text
Worker reports job failure
  │
  ▼
Record error and attempt result
  │
  ├─ Attempts remain
  │    ├─ Calculate exponential backoff with jitter
  │    ├─ Set available_at
  │    └─ Change RUNNING → RETRY_WAIT
  │
  └─ Retry limit reached
       └─ Change job → DEAD_LETTERED

RETRY_WAIT
  │
  ▼
Scheduler finds available_at <= now
  │
  ├─ Lock due rows with SKIP LOCKED
  ├─ Change RETRY_WAIT → QUEUED
  └─ Create JOB_READY outbox event
  │
  ▼
Outbox publisher puts job ID in Redis
  │
  ▼
Worker claims the job again
```

The scheduler and recovery monitor must be safe to restart. Publishing and state changes are idempotent and use the job ID as the deduplication key.

---

# Final Component Design

```text
API Service (FastAPI)
  ├─ validate and submit jobs
  ├─ expose job and worker status
  └─ write PostgreSQL jobs + outbox events

Worker Gateway (FastAPI module)
  ├─ authenticate limited worker tokens
  ├─ register workers and receive heartbeats
  ├─ long-poll and claim jobs through Redis
  ├─ validate lease renewals and terminal reports
  └─ provide payloads and temporary artifact references

PostgreSQL
  ├─ jobs
  ├─ job_attempts
  ├─ workers
  └─ result metadata

Redis
  ├─ named priority queues
  ├─ blocking/long-poll reads
  ├─ tokenized temporary leases
  └─ temporary in-flight claims with deadlines

Outbox Publisher
  ├─ read pending PostgreSQL events
  ├─ publish job IDs to Redis
  └─ mark events published

Worker Processes
  ├─ communicate only with the Worker Gateway
  ├─ register and heartbeat
  ├─ execute approved handlers
  └─ report lease renewal, completion, or failure

Scheduler / Recovery Monitor
  ├─ release delayed and retryable jobs
  ├─ recover expired PostgreSQL leases through retry backoff
  ├─ return timed-out pre-database claims from Redis in-flight to ready
  ├─ reconcile PostgreSQL QUEUED jobs after Redis data loss
  └─ retain exhausted jobs in PostgreSQL as DEAD_LETTERED
```

## Final decisions locked

```text
Code Structure:       Separate API, worker, scheduler, and recovery processes
Core Entity:           Job with explicit lifecycle
Queue Structure:       Named queues with priority
Assignment:            Worker pull
Job Delivery:          Gateway HTTP long poll; internal Redis atomic claim
Control Communication: Worker Gateway REST API
Delivery:              At-least-once
State:                 PostgreSQL source of truth
Worker Trust Boundary: No direct database, Redis, or storage access
Worker Management:     Registration + heartbeats
Failure Recovery:      Job leases + requeue
Retries:               Exponential backoff with jitter
Permanent Failure:     Dead-letter queue
Scheduling:            Separate scheduler
Scaling:               Horizontal workers
```
