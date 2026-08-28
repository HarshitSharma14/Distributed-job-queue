from datetime import datetime, timezone

import pytest

from distributed_job_queue.storage import MinioResultStorage


class FakeMinioClient:
    def __init__(self) -> None:
        self.calls = []

    def presigned_put_object(self, bucket, result_ref, *, expires):
        self.calls.append((bucket, result_ref, expires.total_seconds()))
        return f"https://storage.example.com/{bucket}/{result_ref}?signature=test"


def test_result_storage_creates_attempt_scoped_upload():
    storage = MinioResultStorage(
        "http://localhost:9000",
        "access-key",
        "secret-key",
        "job-results",
    )
    fake_client = FakeMinioClient()
    storage.client = fake_client
    before = datetime.now(timezone.utc)

    upload = storage.create_result_upload(
        job_id="job-1",
        attempt_number=2,
        expires_in_seconds=300,
    )

    assert upload.result_ref == "jobs/job-1/attempts/2/result.json"
    assert fake_client.calls == [
        ("job-results", upload.result_ref, 300.0)
    ]
    assert upload.upload_url.startswith("https://storage.example.com/")
    assert upload.expires_at >= before


@pytest.mark.parametrize(
    "endpoint",
    ["localhost:9000", "ftp://localhost:9000", "http://localhost:9000/path"],
)
def test_result_storage_rejects_invalid_endpoint(endpoint):
    with pytest.raises(ValueError, match="endpoint"):
        MinioResultStorage(endpoint, "access", "secret", "bucket")
