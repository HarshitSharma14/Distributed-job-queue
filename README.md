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
