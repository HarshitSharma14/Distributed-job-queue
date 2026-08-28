"""MinIO-backed result reservations without exposing storage credentials."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from minio import Minio


@dataclass(frozen=True, slots=True)
class ResultUpload:
    result_ref: str
    upload_url: str
    expires_at: datetime


class MinioResultStorage:
    """Create short-lived signed uploads into one private result bucket."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MinIO endpoint must be an http(s) URL")
        if parsed.path not in {"", "/"}:
            raise ValueError("MinIO endpoint must not contain a path")
        if not bucket:
            raise ValueError("MinIO bucket must not be empty")
        self.bucket = bucket
        self.client = Minio(
            parsed.netloc,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
        )

    def create_result_upload(
        self,
        *,
        job_id: str,
        attempt_number: int,
        expires_in_seconds: int,
    ) -> ResultUpload:
        if attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        if expires_in_seconds < 1:
            raise ValueError("expires_in_seconds must be at least 1")
        result_ref = f"jobs/{job_id}/attempts/{attempt_number}/result.json"
        expires = timedelta(seconds=expires_in_seconds)
        upload_url = self.client.presigned_put_object(
            self.bucket,
            result_ref,
            expires=expires,
        )
        return ResultUpload(
            result_ref=result_ref,
            upload_url=upload_url,
            expires_at=datetime.now(timezone.utc) + expires,
        )
