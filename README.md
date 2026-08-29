# Distributed Job Queue

## Local infrastructure

### Prerequisites

- Docker Desktop
- Docker Compose
- Python 3.11 or newer

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

### Stop services

```bash
docker compose down
```

The named Docker volumes preserve local data between restarts. To remove the containers and all local service data:

```bash
docker compose down -v
```

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

## Operational metrics

The API exposes a private Prometheus endpoint using a separate token:

```bash
curl http://localhost:8000/metrics \
  -H 'Authorization: Bearer replace-with-a-long-random-token'
```

Set `METRICS_PORT` to a non-zero internal port when running the scheduler, recovery monitor, or Outbox Publisher as independently scraped processes. Keep these ports private. Publisher-specific dashboard totals come from PostgreSQL; Prometheus is used for operational rates, latency, queue depth, and health trends.

The response includes the current status, active worker and lease expiry when applicable, result reference, error, and ordered attempt history. Internal fencing tokens are never exposed.
