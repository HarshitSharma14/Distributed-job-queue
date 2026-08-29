import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from distributed_job_queue.auth.handler_signing import (
    HandlerSigningError,
    generate_signing_key_pair,
    parse_trusted_public_keys,
    sign_release,
    verify_release,
)


def test_release_signature_binds_identity_version_and_digest():
    private_key = Ed25519PrivateKey.generate()
    private_b64 = base64.b64encode(
        private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    ).decode("ascii")
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    trusted = parse_trusted_public_keys(json.dumps({"key-1": public_b64}))
    signature = sign_release(
        private_b64,
        job_type_id="job-type-1",
        job_type="generate_report",
        version=1,
        digest="a" * 64,
    )

    verify_release(
        trusted,
        key_id="key-1",
        signature_b64=signature,
        job_type_id="job-type-1",
        job_type="generate_report",
        version=1,
        digest="a" * 64,
    )
    with pytest.raises(HandlerSigningError, match="signature is invalid"):
        verify_release(
            trusted,
            key_id="key-1",
            signature_b64=signature,
            job_type_id="job-type-1",
            job_type="generate_report",
            version=2,
            digest="a" * 64,
        )


def test_release_rejects_unknown_signing_key():
    with pytest.raises(HandlerSigningError, match="not trusted"):
        verify_release(
            {},
            key_id="unknown",
            signature_b64="invalid",
            job_type_id="job-type-1",
            job_type="generate_report",
            version=1,
            digest="a" * 64,
        )


def test_generated_signing_pair_can_sign_and_verify():
    pair = generate_signing_key_pair()
    signature = sign_release(
        pair.private_key_b64,
        job_type_id="job-type-1",
        job_type="generate_report",
        version=1,
        digest="b" * 64,
    )
    trusted = parse_trusted_public_keys(
        json.dumps({"generated": pair.public_key_b64})
    )

    verify_release(
        trusted,
        key_id="generated",
        signature_b64=signature,
        job_type_id="job-type-1",
        job_type="generate_report",
        version=1,
        digest="b" * 64,
    )
