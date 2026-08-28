"""Create a human user without exposing passwords in shell history."""

import argparse
from getpass import getpass

from distributed_job_queue.auth.security import hash_password
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.repositories import IdentityRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a dashboard user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--role",
        action="append",
        choices=[role.value for role in UserRole],
        required=True,
        help="Repeat to grant multiple roles",
    )
    args = parser.parse_args()

    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    password_hash = hash_password(password)

    with SessionFactory.begin() as session:
        repository = IdentityRepository(session)
        user = repository.create_user(
            email=args.email,
            display_name=args.name,
            password_hash=password_hash,
        )
        for role in args.role:
            repository.assign_role(user, UserRole(role))
    print(f"Created user {user.email} ({user.id})")
