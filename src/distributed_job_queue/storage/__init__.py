"""Object-storage adapters for durable job artifacts."""

from .minio_results import MinioResultStorage, ResultUpload

__all__ = ["MinioResultStorage", "ResultUpload"]
