"""Generate one Ed25519 key pair for handler-release attestations."""

import argparse
import json
import sys

from distributed_job_queue.auth.handler_signing import generate_signing_key_pair


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a handler signing key")
    parser.add_argument("--key-id", required=True)
    args = parser.parse_args()
    if not args.key_id.strip():
        raise SystemExit("--key-id must not be empty")
    pair = generate_signing_key_pair()
    trusted = json.dumps({args.key_id: pair.public_key_b64}, separators=(",", ":"))
    print("Store the private key only in the API/Admin secret store.", file=sys.stderr)
    print(f"HANDLER_SIGNING_KEY_ID={args.key_id}")
    print(f"HANDLER_SIGNING_PRIVATE_KEY={pair.private_key_b64}")
    print(f"HANDLER_TRUSTED_PUBLIC_KEYS='{trusted}'")
