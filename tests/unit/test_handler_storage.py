import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from distributed_job_queue.storage.minio_handlers import _validate_bundle


def bundle(files: dict[str, str]) -> bytes:
    content = BytesIO()
    with ZipFile(content, "w", compression=ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return content.getvalue()


def valid_files() -> dict[str, str]:
    return {
        "manifest.json": json.dumps(
            {"job_type": "generate_report", "entrypoint": "handler:handle"}
        ),
        "handler.py": "def handle(payload):\n    return payload\n",
    }


def test_valid_handler_bundle_passes_structural_validation():
    assert (
        _validate_bundle(
            bundle(valid_files()),
            expected_job_type="generate_report",
            max_uncompressed_bytes=10_000,
        )
        is None
    )


def test_handler_bundle_rejects_path_traversal():
    files = valid_files()
    files["../escape.py"] = "unsafe"

    reason = _validate_bundle(
        bundle(files),
        expected_job_type="generate_report",
        max_uncompressed_bytes=10_000,
    )

    assert reason == "Handler archive contains an unsafe path"


def test_handler_bundle_requires_matching_manifest_and_entrypoint_module():
    files = valid_files()
    files["manifest.json"] = json.dumps(
        {"job_type": "other_type", "entrypoint": "missing:handle"}
    )

    reason = _validate_bundle(
        bundle(files),
        expected_job_type="generate_report",
        max_uncompressed_bytes=10_000,
    )

    assert reason == "Handler manifest Job Type does not match the definition"


def test_handler_bundle_rejects_excessive_uncompressed_size():
    files = valid_files()
    files["large.txt"] = "x" * 20_000

    reason = _validate_bundle(
        bundle(files),
        expected_job_type="generate_report",
        max_uncompressed_bytes=1_000,
    )

    assert reason == "Handler archive exceeds the uncompressed size limit"
