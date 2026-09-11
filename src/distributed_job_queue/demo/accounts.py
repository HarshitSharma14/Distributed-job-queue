"""Stable identities reserved for the public portfolio demonstration."""

PUBLIC_DEMO_EMAILS = frozenset(
    {
        "publisher.demo@relay.local",
        "producer.demo@relay.local",
        "worker.demo@relay.local",
    }
)


def is_public_demo_account(email: str) -> bool:
    return email.strip().lower() in PUBLIC_DEMO_EMAILS
