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

Large results are stored outside the job row; `result_ref` points to the result location. Small results may be stored inline when appropriate.

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
                         └→ FAILED → DEAD_LETTERED
```

State meanings:

- `CREATED`: request accepted and being persisted.
- `QUEUED`: ready for a worker.
- `RUNNING`: claimed with an active lease.
- `RETRY_WAIT`: failed and waiting for its next attempt.
- `COMPLETED`: finished successfully.
- `FAILED`: permanently failed or awaiting dead-letter handling.
- `DEAD_LETTERED`: exhausted its retry limit.

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

### Choose: Worker pull with atomic claim and long polling

1. Worker long-polls a compatible Redis queue.
2. Redis atomically moves the job from ready to an in-flight set and creates a temporary lease with a unique token.
3. Worker conditionally changes PostgreSQL to `RUNNING`, storing the worker, token, and expiration.
4. Worker renews Redis and PostgreSQL using the same token.

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

### Choose: Redis blocking wait with atomic priority claim

Workers first try an immediate atomic claim. When the priority queue is empty, they block on a per-queue Redis notification list for a bounded period. Enqueueing atomically adds the job to the sorted set and emits a wake-up signal. A woken worker then runs the Lua claim against the sorted set. This avoids repeated empty-queue requests while preserving priority and leases.

## Worker endpoints

```text
POST /workers/register
POST /workers/{worker_id}/heartbeat
POST /jobs/{job_id}/heartbeat
POST /jobs/{job_id}/complete
POST /jobs/{job_id}/fail
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

Workers periodically update `last_heartbeat_at`. Redis holds a short-lived tokenized lease for coordination, while PostgreSQL stores authoritative ownership and expiration. Recovery queries expired `RUNNING` rows, clears ownership with row locking, and writes an outbox event for republication.

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

The scheduler finds `RETRY_WAIT` or delayed `CREATED` jobs where `available_at <= now`, publishes them, and changes them to `QUEUED`. The operation is idempotent so a scheduler restart is safe.

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

Every event includes `job_id`, `worker_id`, `queue`, `attempt`, `status`, and `duration`.

Track:

- queue depth and oldest queued job
- success, failure, retry, and dead-letter counts
- wait and processing time
- active and offline workers
- expired leases

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
  │ Long-poll compatible Redis queue
  ▼
Atomically claim job and create tokenized Redis lease
  │
  ├─ Update PostgreSQL: QUEUED → RUNNING
  ├─ Store worker_id, lease_token, and lease_expires_at
  ├─ Create job-attempt record
  ├─ Renew lease while processing
  └─ Execute handler
       │
       ├─ Success: save result, mark COMPLETED, remove lease
       └─ Failure: record error, calculate retry or dead-letter
```

Only the worker holding the active lease may complete or fail the job. Completion must be idempotent because a lease can expire near the end of execution.

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
  ├─ If attempts remain: create JOB_READY outbox event
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
  ├─ Publish job ID to Redis
  └─ Change RETRY_WAIT → QUEUED
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
  ├─ register and heartbeat
  ├─ pull compatible jobs
  ├─ renew leases
  └─ complete or fail jobs

Scheduler / Recovery Monitor
  ├─ release delayed and retryable jobs
  ├─ recover expired PostgreSQL leases through the outbox
  ├─ return timed-out pre-database claims from Redis in-flight to ready
  ├─ reconcile PostgreSQL QUEUED jobs after Redis data loss
  └─ move exhausted jobs to the dead-letter queue
```

## Final decisions locked

```text
Code Structure:       Separate API, worker, scheduler, and recovery processes
Core Entity:           Job with explicit lifecycle
Queue Structure:       Named queues with priority
Assignment:            Worker pull
Job Delivery:          Redis blocking wait + atomic Lua claim
Control Communication: REST over HTTP
Delivery:              At-least-once
State:                 PostgreSQL source of truth
Worker Management:     Registration + heartbeats
Failure Recovery:      Job leases + requeue
Retries:               Exponential backoff with jitter
Permanent Failure:     Dead-letter queue
Scheduling:            Separate scheduler
Scaling:               Horizontal workers
```
