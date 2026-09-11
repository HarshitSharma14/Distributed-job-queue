"""Idempotent local-stack initialization; never reset existing identities or keys."""

import json
import os
from pathlib import Path

from sqlalchemy import select, text
from distributed_job_queue.auth.handler_signing import generate_signing_key_pair
from distributed_job_queue.auth.security import hash_password
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import User
from distributed_job_queue.persistence.repositories import IdentityRepository


def main():
    directory = Path(os.environ.get("PLATFORM_STATE_DIR", "/var/lib/djq"))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "signing.json"
    if not path.exists():
        key = generate_signing_key_pair()
        # Exclusive creation prevents overwriting persistent signing identity.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(
                {
                    "key_id": "local-platform",
                    "private_key": key.private_key_b64,
                    "public_key": key.public_key_b64,
                },
                out,
            )
    from distributed_job_queue.api.dependencies import (
        get_handler_storage,
        get_result_storage,
    )

    for storage in (get_handler_storage(), get_result_storage()):
        if not storage.client.bucket_exists(storage.bucket):
            storage.client.make_bucket(storage.bucket)
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@relay.local").strip().lower()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    with SessionFactory.begin() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(81472930)"))
        existing = session.scalar(select(User).where(User.email == email))
        if existing is None:
            from distributed_job_queue.persistence.models import UserRoleAssignment

            active_admin = session.scalar(
                select(User.id)
                .join(UserRoleAssignment)
                .where(
                    User.status == "ACTIVE",
                    User.password_hash.is_not(None),
                    UserRoleAssignment.role == "ADMIN",
                )
                .limit(1)
            )
            if active_admin is None:
                if len(password) < 12:
                    raise RuntimeError(
                        "Set BOOTSTRAP_ADMIN_PASSWORD to at least 12 characters for first startup"
                    )
                repo = IdentityRepository(session)
                user = repo.create_user(
                    email=email,
                    display_name="Platform Admin",
                    password_hash=hash_password(password),
                )
                user.password_change_required = True
                repo.assign_role(user, UserRole.ADMIN)
    metrics = Path(os.environ.get("PROMETHEUS_CONFIG_DIR", "/var/lib/djq-metrics"))
    metrics.mkdir(parents=True, exist_ok=True)
    # JSON is valid YAML and avoids shell interpolation of credentials.
    config = {
        "global": {"scrape_interval": "5s"},
        "scrape_configs": [
            {
                "job_name": "api",
                "authorization": {
                    "credentials": os.environ.get(
                        "METRICS_TOKEN", "local-demo-metrics-token"
                    )
                },
                "static_configs": [{"targets": ["api:8000"]}],
            },
            *[
                {"job_name": name, "static_configs": [{"targets": [f"{name}:9100"]}]}
                for name in ("outbox", "scheduler", "recovery")
            ],
        ],
    }
    (metrics / "prometheus.yml").write_text(json.dumps(config))
    print(
        "Local platform initialized; existing accounts and signing identity preserved."
    )


if __name__ == "__main__":
    main()
