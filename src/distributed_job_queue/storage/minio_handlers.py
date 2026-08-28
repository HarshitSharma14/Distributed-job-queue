"""Private MinIO storage for Publisher handler bundles."""

import hashlib
import json
import re
import stat
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile, is_zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from minio import Minio
from minio.commonconfig import CopySource


@dataclass(frozen=True, slots=True)
class HandlerUpload:
    object_ref: str
    upload_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class HandlerInspection:
    size_bytes: int
    digest: str | None
    rejection_reason: str | None


class MinioHandlerStorage:
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

    def create_upload(
        self, *, object_ref: str, expires_in_seconds: int
    ) -> HandlerUpload:
        if not object_ref:
            raise ValueError("object_ref must not be empty")
        if expires_in_seconds < 1:
            raise ValueError("expires_in_seconds must be at least 1")
        expires = timedelta(seconds=expires_in_seconds)
        return HandlerUpload(
            object_ref=object_ref,
            upload_url=self.client.presigned_put_object(
                self.bucket, object_ref, expires=expires
            ),
            expires_at=datetime.now(timezone.utc) + expires,
        )

    def inspect(
        self,
        *,
        object_ref: str,
        expected_size_bytes: int,
        max_size_bytes: int,
        max_uncompressed_bytes: int,
        expected_job_type: str,
    ) -> HandlerInspection:
        metadata = self.client.stat_object(self.bucket, object_ref)
        actual_size = metadata.size
        if actual_size < 1 or actual_size > max_size_bytes:
            return HandlerInspection(
                size_bytes=actual_size,
                digest=None,
                rejection_reason="Handler artifact size is outside the allowed range",
            )
        if actual_size != expected_size_bytes:
            return HandlerInspection(
                size_bytes=actual_size,
                digest=None,
                rejection_reason="Handler artifact size does not match its reservation",
            )

        response = self.client.get_object(self.bucket, object_ref)
        digest = hashlib.sha256()
        content = bytearray()
        try:
            while chunk := response.read(64 * 1024):
                digest.update(chunk)
                content.extend(chunk)
        finally:
            response.close()
            response.release_conn()
        rejection_reason = _validate_bundle(
            bytes(content),
            expected_job_type=expected_job_type,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
        return HandlerInspection(
            size_bytes=actual_size,
            digest=digest.hexdigest(),
            rejection_reason=rejection_reason,
        )

    def remove(self, object_ref: str) -> None:
        self.client.remove_object(self.bucket, object_ref)

    def promote(self, *, source_ref: str, verified_ref: str) -> None:
        """Copy verified bytes to a key never exposed by an upload URL."""

        self.client.copy_object(
            self.bucket,
            verified_ref,
            CopySource(self.bucket, source_ref),
        )


def _validate_bundle(
    content: bytes, *, expected_job_type: str, max_uncompressed_bytes: int
) -> str | None:
    source = BytesIO(content)
    if not is_zipfile(source):
        return "Handler artifact is not a valid ZIP archive"
    source.seek(0)
    try:
        with ZipFile(source) as archive:
            entries = archive.infolist()
            if not entries:
                return "Handler archive is empty"
            total_uncompressed = 0
            names: set[str] = set()
            for entry in entries:
                if "\\" in entry.filename:
                    return "Handler archive contains an unsafe path"
                path = PurePosixPath(entry.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or (path.parts and ":" in path.parts[0])
                ):
                    return "Handler archive contains an unsafe path"
                if entry.filename in names:
                    return "Handler archive contains duplicate paths"
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                    return "Handler archive must not contain symbolic links"
                total_uncompressed += entry.file_size
                if total_uncompressed > max_uncompressed_bytes:
                    return "Handler archive exceeds the uncompressed size limit"
                names.add(entry.filename)
            if archive.testzip() is not None:
                return "Handler archive contains corrupt files"
            if "manifest.json" not in names:
                return "Handler archive must contain manifest.json"
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return "Handler manifest is not valid JSON"
    except BadZipFile:
        return "Handler artifact is not a valid ZIP archive"

    if not isinstance(manifest, dict):
        return "Handler manifest must be a JSON object"
    if manifest.get("job_type") != expected_job_type:
        return "Handler manifest Job Type does not match the definition"
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str) or not re.fullmatch(
        r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entrypoint
    ):
        return "Handler manifest entrypoint is invalid"
    module_name, _ = entrypoint.split(":", 1)
    module_path = module_name.replace(".", "/") + ".py"
    if module_path not in names:
        return "Handler entrypoint module is missing from the archive"
    return None
