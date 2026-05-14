import io
import json
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from minio import Minio
from minio.error import S3Error
from minio.versioningconfig import VersioningConfig

from rag_benchmarking.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    version_id: str | None
    size: int


def get_minio_client(settings: Settings | None = None) -> Minio:
    resolved = settings or get_settings()
    return Minio(
        resolved.minio_endpoint,
        access_key=resolved.minio_access_key,
        secret_key=resolved.minio_secret_key.get_secret_value(),
        secure=resolved.minio_secure,
    )


class ObjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = get_minio_client(self.settings)

    def ensure_buckets(self) -> None:
        for bucket in {self.settings.raw_document_bucket, self.settings.artifact_bucket}:
            started = time.perf_counter()
            logger.info("minio_ensure_bucket_start", bucket=bucket)
            exists = self.client.bucket_exists(bucket)
            if not exists:
                logger.info("minio_make_bucket", bucket=bucket)
                self.client.make_bucket(bucket)
            with suppress(Exception):
                self.client.set_bucket_versioning(bucket, VersioningConfig(status="Enabled"))
            logger.info(
                "minio_ensure_bucket_done",
                bucket=bucket,
                already_existed=exists,
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )

    def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        self.ensure_buckets()
        started = time.perf_counter()
        logger.info("minio_put_object_start", bucket=bucket, key=key, bytes=len(data))
        try:
            result = self.client.put_object(
                bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        except Exception as exc:
            logger.exception(
                "minio_put_object_failed",
                bucket=bucket,
                key=key,
                exception_type=exc.__class__.__name__,
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )
            raise
        logger.info(
            "minio_put_object_done",
            bucket=bucket,
            key=key,
            bytes=len(data),
            version_id=result.version_id,
            elapsed_seconds=round(time.perf_counter() - started, 3),
        )
        return StoredObject(bucket=bucket, key=key, version_id=result.version_id, size=len(data))

    def put_json(self, *, key: str, payload: Any) -> StoredObject:
        data = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
        return self.put_bytes(
            bucket=self.settings.artifact_bucket,
            key=key,
            data=data,
            content_type="application/json",
        )

    def put_text(self, *, key: str, text: str, content_type: str = "text/markdown") -> StoredObject:
        return self.put_bytes(
            bucket=self.settings.artifact_bucket,
            key=key,
            data=text.encode("utf-8"),
            content_type=content_type,
        )

    def put_file(self, *, bucket: str, key: str, path: Path, content_type: str) -> StoredObject:
        data = path.read_bytes()
        return self.put_bytes(bucket=bucket, key=key, data=data, content_type=content_type)

    def get_bytes(self, *, bucket: str, key: str, version_id: str | None = None) -> bytes:
        started = time.perf_counter()
        logger.info("minio_get_object_start", bucket=bucket, key=key, version_id=version_id)
        try:
            try:
                response = self.client.get_object(bucket, key, version_id=version_id)
            except TypeError:
                response = self.client.get_object(bucket, key)
            try:
                data = response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            logger.exception(
                "minio_get_object_failed",
                bucket=bucket,
                key=key,
                version_id=version_id,
                exception_type=exc.__class__.__name__,
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )
            raise
        logger.info(
            "minio_get_object_done",
            bucket=bucket,
            key=key,
            version_id=version_id,
            bytes=len(data),
            elapsed_seconds=round(time.perf_counter() - started, 3),
        )
        return data

    def exists(self, *, bucket: str, key: str) -> bool:
        try:
            self.client.stat_object(bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket"}:
                return False
            raise
        return True
