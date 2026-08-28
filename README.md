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

The `job-results` bucket should exist and remain private.

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
job-worker \
  --name report-worker-1 \
  --queue reports \
  --handler-module project.handlers
```

`--queue` and `--handler-module` may be repeated. If capabilities are not supplied explicitly, the worker advertises its registered job types.

When a handler returns a non-`None` JSON-serializable value, the worker requests a short-lived upload URL from the Worker Gateway, uploads the result to private MinIO storage, and completes the job with the issued object reference. The worker never receives MinIO access credentials.

## Submit a job

Start the API:

```bash
job-api
```

Submit an immediate job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: report-request-42' \
  -d '{
    "type": "generate_report",
    "queue": "reports",
    "payload": {"report_id": 42},
    "priority": 8,
    "max_attempts": 3
  }'
```

The API returns `202 Accepted` with status `CREATED`. The outbox publisher asynchronously delivers the job ID to Redis and changes the durable status to `QUEUED`.

Retrying the same request with the same `Idempotency-Key` returns the original job ID and the header `Idempotency-Replayed: true`. Reusing a key with a different request returns `409 Conflict`. Without this header, every valid submission creates a new job.

Read the authoritative job state and execution history:

```bash
curl http://localhost:8000/jobs/<job_id>
```

The response includes the current status, active worker and lease expiry when applicable, result reference, error, and ordered attempt history. Internal fencing tokens are never exposed.
