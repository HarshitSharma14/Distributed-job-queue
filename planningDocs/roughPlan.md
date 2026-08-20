# Distributed Job Queue — Rough Plan

## Goal

Build a small distributed job-processing platform. Clients submit background work through an API; workers process it asynchronously and reliably, even when a worker fails.

Example jobs: report generation, emails, image processing, AI tasks, and data exports.

## Basic flow

```text
Client → API → Job Queue → Worker(s) → Result Store
```

Clients receive a `job_id` immediately. They can later check whether the job is queued, running, completed, failed, or retrying.

## Core components

- **API:** submit jobs, query status, and register workers.
- **Job queue:** stores pending jobs and serves higher-priority work first.
- **Workers:** claim and execute jobs independently.
- **Result store:** persists job state, results, attempts, and errors.
- **Reliability layer:** retries failed work, detects dead workers, and prevents jobs from being lost.

## Job lifecycle

```text
CREATED → QUEUED → RUNNING → COMPLETED
                         ↘ FAILED → RETRY → RUNNING
```

After the retry limit, move the job to a dead-letter queue for inspection.

## Planned features

1. Submit jobs and track their status.
2. Run multiple workers concurrently.
3. Support priorities and delayed jobs.
4. Add retries with exponential backoff.
5. Add worker registration and heartbeats.
6. Detect timeouts and reassign abandoned jobs.
7. Add a small dashboard or status view for workers and jobs.

## Build order

### Phase 1 — Single-machine queue

Implement the API, queue, worker, and database. Prove the complete submit-to-completion flow.

### Phase 2 — Multiple workers

Run several workers and verify that jobs are distributed without duplicate processing.

### Phase 3 — Reliability

Add failures, retries, timeouts, exponential backoff, and the dead-letter queue.

### Phase 4 — Distributed operation

Add worker discovery, heartbeats, failure detection, and support for workers on separate machines.

## Definition of done

Run an API, two workers, and a client from separate terminals. Submit a job, watch a worker complete it, then stop that worker during processing. The system should detect the failure and allow another worker to finish the job without losing it.

The project should make the main distributed-systems concerns visible: concurrency, scheduling, persistence, retries, and failure recovery.
