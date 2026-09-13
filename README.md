# Distributed Job Queue

## 🚀 Live Production Demo

The Distributed Job Queue control plane is deployed and running live on an Oracle Cloud Infrastructure (OCI) Always Free Tier VM:
- **Web Dashboard**: [https://relay.140-238-241-160.sslip.io/app/login](https://relay.140-238-241-160.sslip.io/app/login)
- **Worker Gateway / API**: `https://relay.140-238-241-160.sslip.io`
- **Object Storage (MinIO)**: `https://storage.relay.140-238-241-160.sslip.io`

### Guided Public Demo Credentials
To explore the role-aware dashboard immediately, log in with our pre-seeded public demo account:
- **Email**: `demo@relay.local`
- **Password**: `relay-demo-password`

This single account is pre-granted **Admin**, **Publisher**, **Producer**, and **Worker Owner** roles, allowing you to walk through the entire lifecycle—from approving custom Python handlers and enrolling worker agents to queuing jobs and observing execution in real-time.

---

## 📚 Architectural & Implementation Documentation

Explore the deep architecture, design patterns, and deployment journey of Relay through our comprehensive technical guides:

| Document | Description |
| :--- | :--- |
| **[System Architecture & Design (HLD/LLD)](planningDocs/HLD+Component_Design+LLD.md)** | Deep-dive into the high-level system components, dual-database consistency (PostgreSQL + Redis), low-level database schemas, API contracts, security bounds, and worker sandboxing specifications. |
| **[Technology Design Specification](planningDocs/Technology_Design.md)** | Details about security design (cryptography, token designs), data pipelines, outbox pattern, recovery logic, database choices, and the worker containerized execution sandbox. |
| **[OCI Production Deployment Walkthrough](planningDocs/Oracle_Always_Free_Deployment_Walkthrough.md)** | A step-by-step checklist and study guide for setting up and deploying this platform to an Oracle Cloud Infrastructure Always Free VM standard ARM64 instance with Canonical Ubuntu, UFW firewalling, and automated Caddy reverse proxy HTTPS. |
| **[Codebase Structure](planningDocs/Structure.md)** | A guide to the layout of the project, detailing the roles of the domain, persistence, API, workers, scheduler, recovery, and test folders. |
| **[Implementation Tracker & Milestone Log](planningDocs/Implementation_Tracker.md)** | Chronological history of engineering milestones, implemented features, and technical enhancements. |
| **[Market Research & Competitors](planningDocs/marketResearch.md)** | Comparison against standard industry solutions (such as Inngest, SQS, RabbitMQ, and Kafka) outlining Relay's unique niche in operator-run environments. |
| **[Production Release Guide](deploy/README.md)** | Operational guides on how to manage, run, back up, restore, and upgrade the production stack using Docker Compose and Caddy. |

---

## Complete local dashboard release

Set `BOOTSTRAP_ADMIN_PASSWORD` (at least 12 characters) in `.env`, then run `docker compose up -d --build` and open [Relay](http://localhost:8000/app/). Admins manage accounts; Publishers upload and release handlers; Producers submit and track jobs; Worker owners enroll agents in the dashboard and copy one execution command.

See [the local release guide](deploy/README.md) for the full browser walkthrough, Worker setup, operational controls, backups, and verification. The sections below describe individual services and development APIs.

## Local infrastructure

### Prerequisites

- Docker Desktop
- Docker Compose
- Python 3.11 or newer
- Node.js 22 or newer for dashboard development

### Configure the environment

Copy the example configuration:

```bash
cp .env.example .env
```

The local services use:

```text
PostgreSQL: localhost:5432
Redis:      localhost:6379
MinIO API:  localhost:9000
MinIO UI:   http://localhost:9001
```

### Start services

```bash
docker compose up -d
```

Check service status:

```bash
docker compose ps
```

### Verify services

```bash
docker compose exec postgres pg_isready -U queue -d queue
docker compose exec redis redis-cli ping
```

Expected results are `accepting connections` and `PONG`.

Open the MinIO console at [http://localhost:9001](http://localhost:9001) with:

```text
Username: minioadmin
Password: minioadmin
```

The `job-results` and `handler-artifacts` buckets should exist and remain private.

### Configure handler release signing

Generate an Ed25519 key pair once for the platform:

```bash
djq-generate-handler-key --key-id local-dev
```

Store `HANDLER_SIGNING_PRIVATE_KEY` only with the API/Admin deployment. Configure workers with `HANDLER_TRUSTED_PUBLIC_KEYS`, which maps the key ID to its public key. Never copy the private key to a worker.

A Publisher upload is verified and promoted as immutable, then remains `PENDING_APPROVAL`. An Admin must approve and sign that exact Job Type ID, name, version, and digest before it becomes `ACTIVE`. Workers verify this release signature before installing the bundle.

### Create a new Job Type version

Create the next immutable draft from the latest active or disabled release:

```bash
curl -X POST http://localhost:8000/job-types/<current_job_type_id>/versions \
  -H 'Content-Type: application/json' \
  -H 'X-CSRF-Token: <csrf-token>' \
  -b 'djq_session=<session-token>; djq_csrf=<csrf-token>' \
  -d '{}'
```

The new row keeps the Publisher and name, increments the version, inherits the queue unless a replacement is supplied, and starts as `DRAFT` with no handler or signature. The previous release remains unchanged for pinned jobs and workers.

### Stop services

```bash
docker compose down
```

The named Docker volumes preserve local data between restarts. To remove the containers and all local service data:

```bash
docker compose down -v
```

## Dashboard development

Install and run the role-aware dashboard:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173/app/](http://localhost:5173/app/). Vite proxies same-origin authentication and dashboard API calls to FastAPI at `http://localhost:8000`.

Build production assets with:

```bash
npm run build
```

FastAPI automatically serves an available `frontend/dist` at `/app`. Set `FRONTEND_DIST_DIR` when deployment places the static bundle elsewhere. API routes remain separate from the SPA fallback.

### Fill the local dashboards with demo data

With PostgreSQL running, seed a repeatable development-only dataset:

```bash
source .venv/bin/activate
python -m distributed_job_queue.demo.seed
```

The command is idempotent and does not modify non-demo records. It creates 40 jobs across all lifecycle states, four historical Job Types, four Workers, attempt history, and multiple owners. Log in with:

```text
Email:    demo@relay.local
Password: relay-demo-password
```

This account has Admin, Publisher, Producer, and Worker roles. The other seeded users create cross-owner records for authorization and Admin visibility. Demo Job Types are disabled historical definitions, preventing accidental execution of synthetic handlers.

### Test database isolation

Pytest never uses the development `queue` database. Integration tests recreate and migrate the dedicated `queue_test` database configured by `TEST_DATABASE_URL`, whose name must end in `_test`. This preserves seeded dashboard data while keeping global Admin and recovery tests deterministic.

Use the `-v` option only when local data can be discarded.

## Worker handler modules

A worker loads application code through modules that explicitly register handlers:

```python
from distributed_job_queue.workers import HandlerRegistry


def generate_report(payload: dict) -> int:
    return payload["report_id"]


def register_handlers(registry: HandlerRegistry) -> None:
    registry.register("generate_report", generate_report)
```

Run a worker subscribed to the matching queue:

```bash
export WORKER_ENROLLMENT_TOKEN='djq_enroll_...'
job-worker \
  --name report-worker-1 \
  --allow-downloaded-handler
```

An authenticated Worker user creates the short-lived enrollment token for one active, Admin-approved Job Type. Registration consumes it once and returns a revocable credential bound to that Worker Agent. The platform—not the worker—selects the Job Type capability and queue. The worker exits if its local bundle does not contain the assigned handler or its platform release signature is invalid.

For trusted internal code, provide `--handler-module` and omit `--allow-downloaded-handler`. For a generic external agent, the opt-in flag executes the assigned bundle only through an ephemeral restricted Docker container. The agent itself never imports Publisher code. Docker must be running on the Worker machine.

The sandbox has no network or host environment, uses read-only filesystems and a non-root user, drops capabilities, and enforces CPU, memory, PID, timeout, and output limits. It currently supports Python standard-library handlers; approved dependency images are a future extension. Docker reduces risk but is not equivalent to microVM isolation for fully hostile multi-tenant workloads.

After registration, the worker uses only its agent credential for handler download, heartbeats, claims, lease renewal, result upload, completion, and failure. It cannot act as another worker, claim another queue or Job Type, or access PostgreSQL, Redis, or permanent storage credentials.

When a handler returns a non-`None` JSON-serializable value, the worker requests a short-lived upload URL from the Worker Gateway, uploads the result to private MinIO storage, and completes the job with the issued object reference. The worker never receives MinIO access credentials.

## Submit a job

Start the API:

```bash
job-api
```

Submit an immediate job:

```bash
export PRODUCER_API_KEY='djq_prod_...'
export JOB_TYPE_ID='job-type-uuid'

curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${PRODUCER_API_KEY}" \
  -H 'Idempotency-Key: report-request-42' \
  -d '{
    "job_type_id": "'"${JOB_TYPE_ID}"'",
    "payload": {"report_id": 42},
    "priority": 8,
    "max_attempts": 3
  }'
```

The API returns `202 Accepted` with status `CREATED`. The outbox publisher asynchronously delivers the job ID to Redis and changes the durable status to `QUEUED`.

Retrying the same request with the same `Idempotency-Key` returns the original job ID and the header `Idempotency-Replayed: true`. Reusing a key with a different request returns `409 Conflict`. Without this header, every valid submission creates a new job.

Read the authoritative job state and execution history:

```bash
curl http://localhost:8000/jobs/<job_id> \
  -H "Authorization: Bearer ${PRODUCER_API_KEY}"
```

## Publisher dashboard data

An authenticated Publisher browser session can list only jobs created from its Job Types:

```text
GET /publisher/jobs?status=RUNNING&job_type_id=<uuid>&limit=50
```

The response contains lightweight summaries and an opaque `next_cursor`. Pass that cursor to fetch the next stable page. Use `GET /jobs/{job_id}` for the complete payload, result, error, and attempt history.

Exact Publisher analytics are available from:

```text
GET /publisher/analytics?job_type_id=<uuid>&created_after=<timestamp>
```

These totals come from PostgreSQL and include status counts, attempts, terminal success rate, completion latency, and per-version Job Type breakdowns. Both endpoints always enforce the logged-in Publisher's ownership.

## Producer dashboard data

A Producer can use its browser session or a Producer API key with `jobs:read-own`:

```bash
curl 'http://localhost:8000/producer/jobs?status=COMPLETED&limit=50' \
  -H "Authorization: Bearer ${PRODUCER_API_KEY}"

curl 'http://localhost:8000/producer/analytics?publisher_id=<uuid>' \
  -H "Authorization: Bearer ${PRODUCER_API_KEY}"
```

Both endpoints are always restricted to jobs submitted by that Producer. Lists can be narrowed by Publisher, Job Type, status, and creation window. Analytics include exact lifecycle totals and identify the Publisher for each Job Type breakdown. Use `GET /jobs/{job_id}` for the complete authorized payload, result, error, and attempt history.

## Worker dashboard data

An authenticated Worker user can inspect current work across owned agents:

```text
GET /worker-management/assignments?worker_id=<agent-id>
```

Execution history is cursor paginated and filterable:

```text
GET /worker-management/attempts?status=FAILED&job_type_id=<uuid>&limit=50
```

These dashboard routes expose safe assignment metadata, attempt outcomes, errors, and durations. They never return job payloads, result references, lease tokens, Worker credentials, or another user's agents. Execution payloads remain available only to the assigned Worker Agent through the Worker Gateway.

## Admin control-plane data

An authenticated Admin browser session can access:

```text
GET /admin/jobs
GET /admin/analytics
GET /admin/overview?window=24h
GET /admin/workers
GET /admin/queues
GET /admin/dead-letters
```

Admin jobs support Publisher, Producer, Job Type, queue, status, time, and cursor filters. Worker records include owner, capabilities, health, heartbeat, and active-job count. Queue records show PostgreSQL lifecycle totals separately from Redis ready and in-flight depth. Dead-letter summaries link to `GET /jobs/{job_id}` for complete payload, result, error, and attempt history.

Admin responses still never reveal passwords, bearer tokens, credential hashes, signing secrets, signed URLs, infrastructure credentials, or lease tokens.

`GET /admin/overview` returns exact global PostgreSQL analytics together with Admin-only operational Prometheus trends. Supported windows are `1h`, `6h`, `24h`, and `7d`. The operational series cover submission rate, attempt outcomes, p95 execution latency, queue depth, lease losses, recovery, offline Workers, and state-collector health. If Prometheus is unavailable, exact PostgreSQL totals still succeed and `operational.available` is `false`.

## Operational metrics

The API exposes a private Prometheus endpoint using a separate token:

```bash
curl http://localhost:8000/metrics \
  -H 'Authorization: Bearer replace-with-a-long-random-token'
```

Set `METRICS_PORT` to a non-zero internal port when running the scheduler, recovery monitor, or Outbox Publisher as independently scraped processes. Keep these ports private. Publisher-specific dashboard totals come from PostgreSQL; Prometheus is used for operational rates, latency, queue depth, and health trends.

Set `PROMETHEUS_URL` on the API to enable Admin trend queries. A hosted Prometheus-compatible service may also use `PROMETHEUS_USERNAME` and `PROMETHEUS_PASSWORD`; configure both or neither. PromQL is fixed by the backend, queries run with a bounded timeout, and browser clients never receive Prometheus credentials or direct query access.

The response includes the current status, active worker and lease expiry when applicable, result reference, error, and ordered attempt history. Internal fencing tokens are never exposed.
