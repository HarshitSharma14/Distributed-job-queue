from uuid import uuid4

import httpx

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.storage import MinioResultStorage


def test_signed_result_upload_reaches_private_minio_bucket():
    settings = load_settings()
    storage = MinioResultStorage(
        settings.minio_endpoint,
        settings.minio_access_key,
        settings.minio_secret_key,
        settings.minio_bucket,
    )
    assert storage.client.bucket_exists(settings.minio_bucket)
    job_id = str(uuid4())
    upload = storage.create_result_upload(
        job_id=job_id,
        attempt_number=1,
        expires_in_seconds=60,
    )
    payload = b'{"report_id":42}'

    try:
        response = httpx.put(
            upload.upload_url,
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200

        stored = storage.client.get_object(settings.minio_bucket, upload.result_ref)
        try:
            assert stored.read() == payload
        finally:
            stored.close()
            stored.release_conn()
    finally:
        storage.client.remove_object(settings.minio_bucket, upload.result_ref)
