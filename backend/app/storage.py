"""Original resume files (PDF, DOCX, TXT), so recruiters can download what the candidate sent.

- local: files under STORAGE_DIR. In Docker, mount a volume there (docker-compose does).
- s3:    any S3-compatible bucket: AWS S3, Cloudflare R2, MinIO. Downloads use short-lived
         presigned URLs, so the bucket stays private.
- none:  keep only the extracted text.

Keys are generated here (never taken from user input), so a filename can't escape the store.
"""

import logging
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .config import Settings, get_settings

log = logging.getLogger(__name__)

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def content_type(filename: str) -> str:
    return CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


class Storage(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def download_url(self, key: str, filename: str) -> str | None:
        """A URL the browser can download from directly, or None to stream through the API."""
        ...


class LocalStorage:
    name = "local"

    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    def download_url(self, key: str, filename: str) -> str | None:
        return None


class S3Storage:
    name = "s3"

    def __init__(self, s: Settings):
        import boto3

        if not s.s3_bucket:
            raise RuntimeError("STORAGE_PROVIDER=s3 needs S3_BUCKET")
        self.bucket = s.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region or None,
            aws_access_key_id=s.s3_access_key_id or None,
            aws_secret_access_key=s.s3_secret_access_key or None,
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def download_url(self, key: str, filename: str) -> str | None:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key, "ResponseContentDisposition": disposition(filename)},
            ExpiresIn=300,
        )


@lru_cache
def get_storage() -> Storage | None:
    s = get_settings()
    if s.storage_provider == "none":
        return None
    if s.storage_provider == "s3":
        return S3Storage(s)
    return LocalStorage(s.storage_dir)


def safe_filename(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name).strip("._") or "resume"
    return name[-120:]


def disposition(filename: str) -> str:
    return f'attachment; filename="{safe_filename(filename)}"'


def save_resume(filename: str, data: bytes) -> str | None:
    """Store an original resume; returns its key, or None when storage is off or fails.
    A storage outage must not lose the candidate, so failures are logged, not raised."""
    storage = get_storage()
    if storage is None:
        return None
    key = f"resumes/{uuid.uuid4().hex}/{safe_filename(filename)}"
    try:
        storage.put(key, data, content_type(filename))
    except Exception:  # noqa: BLE001
        log.exception("Couldn't store the original resume %r; keeping the extracted text only", filename)
        return None
    return key


def delete_resume(key: str | None) -> None:
    storage = get_storage()
    if key and storage is not None:
        try:
            storage.delete(key)
        except Exception:  # noqa: BLE001
            log.exception("Couldn't delete stored resume %s", key)
