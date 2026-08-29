"""Ed25519 release attestations for approved immutable handler bundles."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization


class HandlerSigningError(ValueError):
    """Raised for missing, malformed, unknown, or invalid signing material."""


@dataclass(frozen=True, slots=True)
class HandlerSigningKeyPair:
    private_key_b64: str
    public_key_b64: str


def generate_signing_key_pair() -> HandlerSigningKeyPair:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return HandlerSigningKeyPair(
        private_key_b64=base64.b64encode(private_bytes).decode("ascii"),
        public_key_b64=base64.b64encode(public_bytes).decode("ascii"),
    )


def release_message(
    *, job_type_id: str, job_type: str, version: int, digest: str
) -> bytes:
    return json.dumps(
        {
            "digest": digest.lower(),
            "job_type": job_type,
            "job_type_id": job_type_id,
            "purpose": "djq-handler-release-v1",
            "version": version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def sign_release(
    private_key_b64: str,
    *,
    job_type_id: str,
    job_type: str,
    version: int,
    digest: str,
) -> str:
    try:
        private_bytes = base64.b64decode(private_key_b64, validate=True)
        private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    except (ValueError, TypeError) as exc:
        raise HandlerSigningError("Handler signing private key is invalid") from exc
    signature = private_key.sign(
        release_message(
            job_type_id=job_type_id,
            job_type=job_type,
            version=version,
            digest=digest,
        )
    )
    return base64.b64encode(signature).decode("ascii")


def parse_trusted_public_keys(encoded: str) -> dict[str, Ed25519PublicKey]:
    try:
        values = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise HandlerSigningError("Trusted handler keys must be valid JSON") from exc
    if not isinstance(values, dict):
        raise HandlerSigningError("Trusted handler keys must be a JSON object")
    parsed: dict[str, Ed25519PublicKey] = {}
    for key_id, public_key_b64 in values.items():
        if not isinstance(key_id, str) or not key_id or not isinstance(public_key_b64, str):
            raise HandlerSigningError("Trusted handler key entry is invalid")
        try:
            public_bytes = base64.b64decode(public_key_b64, validate=True)
            parsed[key_id] = Ed25519PublicKey.from_public_bytes(public_bytes)
        except (ValueError, TypeError) as exc:
            raise HandlerSigningError(
                f"Trusted handler public key {key_id} is invalid"
            ) from exc
    return parsed


def verify_release(
    trusted_keys: dict[str, Ed25519PublicKey],
    *,
    key_id: str,
    signature_b64: str,
    job_type_id: str,
    job_type: str,
    version: int,
    digest: str,
) -> None:
    public_key = trusted_keys.get(key_id)
    if public_key is None:
        raise HandlerSigningError(f"Handler signing key {key_id} is not trusted")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public_key.verify(
            signature,
            release_message(
                job_type_id=job_type_id,
                job_type=job_type,
                version=version,
                digest=digest,
            ),
        )
    except (ValueError, InvalidSignature) as exc:
        raise HandlerSigningError("Handler release signature is invalid") from exc
