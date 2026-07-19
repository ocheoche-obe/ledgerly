"""S3 persistence adapter (boto3) — the upload bucket seam.

Bank CSVs are uploaded straight from the browser to S3 via a presigned PUT URL — the file
never transits Lambda (architecture §2.3, §3.1). The API Lambda mints the URL; S3 then fires
an event that triggers the import Lambda. The object key encodes who + which import so the
import Lambda can attribute the file without trusting anything client-supplied:

    <sub>/<importId>.csv

Both components are server-generated (Cognito sub + a ULID), so the key is unambiguous and
carries no user-controlled text.
"""
from __future__ import annotations

import os
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config

_BUCKET = os.environ["UPLOAD_BUCKET"]
_URL_TTL_SECONDS = 300  # the owner uploads immediately after requesting the URL

# SigV4 is required for presigned PUTs to work across all regions/buckets.
_s3 = boto3.client("s3", config=Config(signature_version="s3v4"))


def upload_key(sub: str, import_id: str) -> str:
    return f"{sub}/{import_id}.csv"


def parse_upload_key(key: str) -> tuple[str, str]:
    """Recover ``(sub, importId)`` from an S3 object key (as delivered in an S3 event).

    S3 event keys are URL-encoded, so unquote first. Raises ValueError on a key that doesn't
    match the ``<sub>/<importId>.csv`` shape (a stray object we won't process).
    """
    decoded = unquote_plus(key)
    if not decoded.endswith(".csv") or decoded.count("/") != 1:
        raise ValueError(f"unexpected upload key: {key!r}")
    sub, filename = decoded.split("/", 1)
    import_id = filename[: -len(".csv")]
    if not sub or not import_id:
        raise ValueError(f"unexpected upload key: {key!r}")
    return sub, import_id


def generate_upload_url(sub: str, import_id: str) -> str:
    """A presigned PUT URL for the browser to upload one CSV to (architecture §3.1)."""
    return _s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": _BUCKET, "Key": upload_key(sub, import_id)},
        ExpiresIn=_URL_TTL_SECONDS,
    )


def get_object_bytes(key: str) -> bytes:
    """Read an uploaded object's raw bytes (import Lambda side)."""
    return _s3.get_object(Bucket=_BUCKET, Key=key)["Body"].read()
