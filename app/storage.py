"""
S3 storage for candidate profiles.

Reads credentials from .env (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
AWS_DEFAULT_REGION, S3_BUCKET_NAME).

Key layout:
  profiles/<candidate_id>_<slug_name>.json   — single candidate
  profiles/batch_<timestamp>/<n>_<slug>.json — batch run
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_BUCKET  = os.getenv("S3_BUCKET_NAME", "")
_REGION  = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
_PREFIX  = "profiles/"


def _client():
    return boto3.client(
        "s3",
        aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name           = _REGION,
    )


def _slug(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(text or "unknown"))[:max_len].strip("_")


def upload_profile(profile: dict[str, Any], key: str | None = None) -> str:
    """
    Upload a single candidate profile dict to S3.
    Returns the S3 key (relative path, no bucket name).
    """
    if not _BUCKET:
        raise RuntimeError("S3_BUCKET_NAME not set in .env")

    if key is None:
        cid  = profile.get("candidate_id") or f"cand_{int(time.time())}"
        name = _slug(profile.get("full_name") or cid)
        key  = f"{_PREFIX}{cid}_{name}.json"

    body = json.dumps(profile, indent=2, default=str, ensure_ascii=False).encode("utf-8")
    _client().put_object(
        Bucket      = _BUCKET,
        Key         = key,
        Body        = body,
        ContentType = "application/json",
    )
    return key


def upload_batch(profiles: list[dict[str, Any]]) -> list[str]:
    """
    Upload a batch of candidate profiles under a common timestamped prefix.
    Returns list of S3 keys (one per candidate).
    """
    ts   = int(time.time())
    keys = []
    for i, p in enumerate(profiles, 1):
        if p.get("_error"):
            continue
        name = _slug(p.get("full_name") or p.get("_batch_label") or f"cand{i}")
        key  = f"{_PREFIX}batch_{ts}/{i:03d}_{name}.json"
        upload_profile(p, key=key)
        keys.append(key)
    return keys


def list_profiles(prefix: str = _PREFIX, max_keys: int = 200) -> list[dict]:
    """
    List stored profiles. Returns list of dicts:
      { key, name, candidate_id, confidence, size, last_modified }
    """
    if not _BUCKET:
        return []

    try:
        resp = _client().list_objects_v2(Bucket=_BUCKET, Prefix=prefix, MaxKeys=max_keys)
    except ClientError as e:
        raise RuntimeError(f"S3 list failed: {e}") from e

    items = []
    for obj in resp.get("Contents", []):
        k = obj["Key"]
        if not k.endswith(".json"):
            continue
        items.append({
            "key":           k,
            "display_name":  Path(k).stem,
            "size":          obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
        })
    return items


def get_profile(key: str) -> dict[str, Any]:
    """Fetch and parse a single profile from S3."""
    if not _BUCKET:
        raise RuntimeError("S3_BUCKET_NAME not set in .env")

    try:
        resp = _client().get_object(Bucket=_BUCKET, Key=key)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            raise KeyError(f"Profile not found: {key}") from e
        raise RuntimeError(f"S3 get failed: {e}") from e

    return json.loads(resp["Body"].read().decode("utf-8"))


def delete_profile(key: str) -> None:
    """Delete a profile from S3."""
    if not _BUCKET:
        raise RuntimeError("S3_BUCKET_NAME not set in .env")
    _client().delete_object(Bucket=_BUCKET, Key=key)
