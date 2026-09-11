# Runnable local release

Requires Docker Desktop/Engine with Compose. Worker execution additionally needs Python 3.11+ and a running Docker daemon. The platform itself needs no host Python or Node installation.

## Start

1. Copy `.env.example` to `.env` if you do not already have a configuration.
2. Set `BOOTSTRAP_ADMIN_EMAIL` and a unique `BOOTSTRAP_ADMIN_PASSWORD` of at least 12 characters.
3. Run `docker compose up -d --build` from the repository root.
4. Open <http://localhost:8000/app/> and sign in. Replace the temporary password when prompted.

`docker compose ps` shows the services. `curl --fail http://localhost:8000/health/ready` confirms database, Redis, and storage readiness. An exited-successfully `init` or `minio-init` container is normal. Initialization applies migrations, creates private buckets, generates persistent signing keys, and creates the first human Admin. It never resets existing passwords or signing identity. Initialization runs as root only to manage named-volume ownership; application services run as UID 1000.

The default stack binds published ports to localhost. It is a local demo configuration, with development infrastructure credentials and HTTP cookies. Use the production override below for public hosting, TLS, and private service ports. Prometheus and process metrics are internal; only the Admin API exposes operational trends. Rate limits, external secret management, and scheduled off-host backups remain future hardening work.

## Production VM deployment

The production override adds Caddy for automatic HTTPS, secure authentication cookies, public Worker and object-storage URLs, and removes every host port except 80 and 443. PostgreSQL, Redis, MinIO, Prometheus, and the API remain reachable only on the private Compose network.

Before the first launch:

1. Point the DNS `A` records for the application and storage subdomains at the VM's public IP. Both names are required because Workers download signed handler bundles and upload results directly to object storage.
2. Copy `deploy/.env.production.example` to `deploy/.env.production`, replace every example value, and run `chmod 600 deploy/.env.production`. `POSTGRES_PASSWORD` and the password embedded in `DATABASE_URL` must match; URL-encode the embedded password if it contains URI-reserved characters.
3. Keep only ports 22, 80, and 443 open in the OCI security list and host firewall. Port 22 should be restricted to the administrator's source IP where practical.
4. Validate and launch from the repository root:

```sh
docker compose --env-file deploy/.env.production \
  -f compose.yaml -f compose.production.yaml config --quiet
docker compose --env-file deploy/.env.production \
  -f compose.yaml -f compose.production.yaml up -d --build
```

Caddy obtains and renews certificates after DNS resolves and ports 80/443 reach the VM. Verify both endpoints and the private port set:

```sh
curl --fail "https://$RELAY_DOMAIN/health/ready"
curl --fail --head "https://$RELAY_DOMAIN/app/"
docker compose --env-file deploy/.env.production \
  -f compose.yaml -f compose.production.yaml ps
sudo ss -lntp
```

The application should redirect to `/app/login`; the storage hostname may return an XML response at its root, which confirms MinIO is reachable without exposing its management console. Run a real Worker enrollment and completed job before considering deployment accepted. Back up the named volumes before every later migration-bearing release.

## Browser walkthrough

- **Admin → Accounts:** create separate Publisher, Producer, and Worker accounts, each with a temporary password. Assign multiple roles if useful. Users must replace temporary passwords before product access. Disabling an account or removing roles revokes existing sessions, Producer keys, Worker enrollments, and agent credentials. Keep one active human Admin.
- **Publisher → Job Types & releases:** create a draft, download its example ZIP, edit the handler locally if desired, and upload the archive. The browser handles validation and shows `PENDING_APPROVAL`. Invalid archives show their rejection reason. The ZIP must contain `manifest.json` with the matching `job_type` and an `entrypoint` such as `handler:run`, plus the referenced Python module.
- **Admin → Releases:** inspect artifact metadata and approve/sign or reject with a reason. Reloading preserves review history. Publishers can create the next immutable version or disable a release.
- **Worker → Worker Agents:** choose an approved release, name the agent, and create an enrollment. Copy the displayed command once. It contains the public trust configuration and short-lived enrollment token, never infrastructure credentials or the private signing key.
- **Producer → Submit a job:** select the release, enter a JSON object, priority, and maximum attempts. Follow status and attempt history; download the completed JSON result.
- **Admin → Queues:** pause new execution claims while existing work finishes, then resume. Submissions and retries remain durable while paused.
- **Producer → Jobs / Admin → Dead letters:** replay an exhausted job as a new job linked to the original. Payload, ownership, priority, attempts limit, and release version are preserved; that release must still be active. Cancellation is not included.
- **Admin → Action history:** inspect account, release, replay, queue, and revocation actions. Worker owners can revoke their own agents; Admins can revoke any agent. Producer API keys are optional for programmatic integrations.

The example handler returns its input. Submit `{"fail": true}` with a small maximum-attempt count to demonstrate retries and dead letters. Executable handlers are distinct from the optional historical demo-data seeder.

## Run a Worker

Install once from this checkout, in a separate terminal:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then paste the command from **Worker Agents**. It runs the approved bundle in an ephemeral Docker sandbox with no network, standard-library Python, and resource/time limits. Stop with Ctrl+C. On restart, create a fresh enrollment in the dashboard and reuse the same agent name. Enrollment tokens are consumed once; agent credentials expire after 24 hours by default.

The Worker Gateway and signed MinIO URLs must both be reachable from the Worker host. Compose generates signed URLs using `localhost:${MINIO_PORT:-9000}` while API storage access uses `minio:9000`. For this localhost-only release, run the Worker on the same machine. During Vite development, use the API address for Workers or the configured dev proxy.

## Restart and upgrade

```sh
docker compose stop
docker compose up -d --build
```

Named volumes retain PostgreSQL, object storage, signing keys, and metrics. Never use `down -v` on data you want to keep. After changing bootstrap environment values, existing accounts are intentionally unchanged; manage them from Accounts. Back up before applying migrations. Queue pause state is stored in PostgreSQL and survives service restarts. Redis is temporary coordination; reconciliation restores queued work from PostgreSQL.

## Backup and restore

Use a consistent offline backup. Set the project name to the name shown by `docker compose ls` (the default for this directory is `distributed_job_queue`). These archives contain private signing material and user data; keep them private.

```sh
mkdir -m 700 -p backups
# Stop writes, including any external Worker first.
docker compose stop api outbox scheduler recovery
docker compose exec -T postgres pg_dump -U queue -d queue -Fc > backups/queue.dump
docker run --rm --user 0 -v distributed_job_queue_minio_data:/data:ro relay-local:dev tar czf - -C /data . > backups/minio.tar.gz
docker run --rm --user 0 -v distributed_job_queue_platform_state:/data:ro relay-local:dev tar czf - -C /data . > backups/signing.tar.gz
chmod 600 backups/*
docker compose up -d
```

Restore into a **new, empty Compose project**, never over a live instance. Start only its PostgreSQL service, restore `queue.dump` with `pg_restore -U queue -d queue --clean --if-exists`, and restore the object and signing archives into that project's corresponding named volumes before starting `init` or `api`. For example, after creating the new named volumes:

```sh
docker compose -p relay-restored up -d postgres
# Wait for PostgreSQL to become healthy.
docker compose -p relay-restored exec -T postgres pg_restore -U queue -d queue --clean --if-exists < backups/queue.dump
docker volume create relay-restored_minio_data
docker volume create relay-restored_platform_state
docker run --rm -i --user 0 -v relay-restored_minio_data:/data relay-local:dev tar xzf - -C /data < backups/minio.tar.gz
docker run --rm -i --user 0 -v relay-restored_platform_state:/data relay-local:dev tar xzf - -C /data < backups/signing.tar.gz
docker compose -p relay-restored up -d
```

Stop the original stack or select unused port overrides before starting the restored project. Redis and Prometheus history are not required to restore jobs. Verify an existing login, release signature, completed result download, and queued-job execution after restoration.

## Verification

```sh
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
DATABASE_URL=postgresql+psycopg://queue:queue@localhost:5432/queue_test alembic check
cd frontend
npm ci
npm test
npm run build
npx playwright install chromium
E2E_BASE_URL=http://localhost:8000 E2E_ADMIN_PASSWORD='<current-admin-password>' npm run test:e2e
```

Pytest recreates only a database whose name ends in `_test`. Run browser acceptance against a dedicated Compose project: it creates accounts/releases/jobs and starts a real local Worker. The browser test replaces a temporary Admin password by appending `-changed`; supply the resulting current password on later runs. Tokens and passwords are excluded from traces. CI runs infrastructure, migrations, backend tests, frontend tests/build, and the same browser flow.
