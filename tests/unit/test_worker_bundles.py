import hashlib
import json
import base64
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from distributed_job_queue.workers.bundles import (
    InvalidDownloadedHandler,
    install_downloaded_handler,
)
from distributed_job_queue.workers.gateway_client import DownloadedHandlerBundle
from distributed_job_queue.workers.handlers import HandlerRegistry
from distributed_job_queue.auth.handler_signing import parse_trusted_public_keys, sign_release


PRIVATE_KEY = Ed25519PrivateKey.generate()
PRIVATE_KEY_B64 = base64.b64encode(
    PRIVATE_KEY.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
).decode("ascii")
PUBLIC_KEY_B64 = base64.b64encode(
    PRIVATE_KEY.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
).decode("ascii")
TRUSTED_KEYS = parse_trusted_public_keys(json.dumps({"test-key": PUBLIC_KEY_B64}))


class RecordingSandbox:
    def __init__(self):
        self.calls = []

    def execute(self, root, entrypoint, payload):
        self.calls.append((root, entrypoint, payload))
        return payload["report_id"]


def make_bundle(files: dict[str, str]) -> DownloadedHandlerBundle:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    encoded = output.getvalue()
    digest = hashlib.sha256(encoded).hexdigest()
    return DownloadedHandlerBundle(
        job_type_id="job-type-1",
        job_type="generate_report",
        version=1,
        digest=digest,
        signing_key_id="test-key",
        release_signature=sign_release(
            PRIVATE_KEY_B64,
            job_type_id="job-type-1",
            job_type="generate_report",
            version=1,
            digest=digest,
        ),
        content=encoded,
    )


def valid_files() -> dict[str, str]:
    return {
        "manifest.json": json.dumps(
            {"job_type": "generate_report", "entrypoint": "handler:handle"}
        ),
        "handler.py": "def handle(payload):\n    return payload['report_id']\n",
    }


def test_downloaded_handler_is_loaded_only_into_assigned_registry():
    registry = HandlerRegistry()
    sandbox = RecordingSandbox()
    installed = install_downloaded_handler(
        registry,
        make_bundle(valid_files()),
        max_uncompressed_bytes=10_000,
        sandbox=sandbox,
        trusted_public_keys=TRUSTED_KEYS,
    )
    try:
        assert registry.handler("generate_report")({"report_id": 42}) == 42
        assert sandbox.calls[0][1:] == (
            "handler:handle",
            {"report_id": 42},
        )
    finally:
        installed.close()


def test_downloaded_handler_rejects_unsafe_archive_paths():
    files = valid_files()
    files["../escape.py"] = "unsafe"

    with pytest.raises(InvalidDownloadedHandler, match="unsafe path"):
        install_downloaded_handler(
            HandlerRegistry(),
            make_bundle(files),
            max_uncompressed_bytes=10_000,
            sandbox=RecordingSandbox(),
            trusted_public_keys=TRUSTED_KEYS,
        )


def test_downloaded_handler_rejects_signature_for_different_release():
    bundle = make_bundle(valid_files())
    altered = DownloadedHandlerBundle(
        job_type_id=bundle.job_type_id,
        job_type="different_job_type",
        version=bundle.version,
        digest=bundle.digest,
        signing_key_id=bundle.signing_key_id,
        release_signature=bundle.release_signature,
        content=bundle.content,
    )

    with pytest.raises(ValueError, match="signature is invalid"):
        install_downloaded_handler(
            HandlerRegistry(),
            altered,
            max_uncompressed_bytes=10_000,
            sandbox=RecordingSandbox(),
            trusted_public_keys=TRUSTED_KEYS,
        )
