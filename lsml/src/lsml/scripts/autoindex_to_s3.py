"""
Stream files from any nginx autoindex directory into S3 (MinIO/Garage).

The source is an nginx autoindex HTML page. The file list is parsed from the
index, then every matching file (by a simple name prefix) is streamed straight
from the HTTP server to S3 with the MinIO client — no local disk, no full-file
buffering. Each file is stored under ``<out-prefix>/<filename>``; any
sub-directory/date structure is just whatever the user puts in the source URL
and the target out prefix. Objects that already exist in S3 are skipped (not
re-uploaded).

S3 configuration: CLI flags take precedence over environment variables
(never hard-code secrets):
  --endpoint    SEGDETE_S3_ENDPOINT   (default favstimacmini.local:3900)
  --access-key  SEGDETE_S3_ACCESS_KEY
  --secret-key  SEGDETE_S3_SECRET_KEY
  --bucket      SEGDETE_S3_BUCKET     (default segdete)
  --out-prefix  SEGDETE_S3_IN_PREFIX  (default in)
  --region      SEGDETE_S3_REGION     (default garage — Garage S3 requires this specific region)
"""

import argparse
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request

from minio import Minio
from minio.error import S3Error

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_HREF_RE = re.compile(r'href="([^"/]+)"')
_UA = "autoindex_to_s3"

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _content_type(name):
    ext = os.path.splitext(name)[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _open(url, method="GET", timeout=120):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": _UA})
    return urllib.request.urlopen(req, timeout=timeout)


def _index_files(source):
    with _open(source) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return sorted(set(_HREF_RE.findall(html)))


def _head_size(url):
    with _open(url, method="HEAD") as resp:
        return int(resp.headers.get("Content-Length") or 0)


def _minio(endpoint, access, secret, region):
    return Minio(
        endpoint,
        access_key=access,
        secret_key=secret,
        secure=False,
        region=region,
    )


def _put_stream(client, bucket, key, url, length, content_type):
    src = _open(url, method="GET", timeout=180)
    try:
        client.put_object(
            bucket,
            key,
            src,
            length=length,
            content_type=content_type,
        )
    finally:
        src.close()


def _existing_size(client, bucket, key):
    try:
        return client.stat_object(bucket, key).size
    except S3Error as exc:
        if exc.code == "NoSuchKey":
            return None
        raise


def _upload(client, bucket, key_prefix, url_base, names, retries):
    uploaded = {}
    total = len(names)
    for i, name in enumerate(names, 1):
        url = f"{url_base}/{name}"
        key = f"{key_prefix}/{name}"
        content_type = _content_type(name)

        existing = _existing_size(client, bucket, key)
        if existing is not None:
            uploaded[key] = existing
            logger.info("[%d/%d] skip (already exists) s3://%s/%s",
                        i, total, bucket, key)
            continue

        for attempt in range(1, retries + 1):
            try:
                size = _head_size(url)
                _put_stream(client, bucket, key, url, size, content_type)
                uploaded[key] = size
                logger.info(
                    "[%d/%d] uploaded s3://%s/%s (%.1f MB)",
                    i, total, bucket, key, size / 1e6,
                )
                break
            except (urllib.error.URLError, OSError) as exc:
                if attempt < retries:
                    wait = 2 * attempt
                    logger.warning(
                        "attempt %d failed for %s (%s); retrying in %ds",
                        attempt, name, exc, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error("giving up on %s: %s", name, exc)
                    raise
    return uploaded


def _verify(client, bucket, key_prefix, uploaded):
    expect = dict(uploaded)
    actual = {
        obj.object_name: obj.size
        for obj in client.list_objects(bucket, prefix=key_prefix, recursive=True)
    }
    missing = sorted(set(expect) - set(actual))
    size_mismatch = sorted(k for k in expect if k in actual and actual[k] != expect[k])
    extra = sorted(set(actual) - set(expect))
    if missing or size_mismatch:
        logger.error(
            "VERIFY FAILED: missing=%d size_mismatch=%d extra=%d",
            len(missing), len(size_mismatch), len(extra),
        )
        for k in missing:
            logger.error("  missing %s", k)
        for k in size_mismatch:
            logger.error("  size mismatch %s expected=%d got=%d",
                         k, expect[k], actual[k])
        for k in extra:
            logger.error("  extra %s", k)
        return False
    logger.info(
        "verified %d objects under %s/ (all sizes match)",
        len(actual), key_prefix,
    )
    return True


def main():
    ap = argparse.ArgumentParser(
        description="Stream files from an nginx autoindex directory into S3"
    )
    ap.add_argument("--source", required=True,
                    help="URL of an autoindex directory (nginx autoindex HTML)")
    ap.add_argument("--image-prefix", default="img_1",
                    help="only upload files whose name starts with this prefix")
    ap.add_argument("--retries", type=int, default=3,
                    help="per-file retries on transient errors (default: 3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="only list the files that would be uploaded")
    ap.add_argument(
        "--endpoint",
        default=os.environ.get("SEGDETE_S3_ENDPOINT", "favstimacmini.local:3900"),
        help="S3 endpoint host:port (env: SEGDETE_S3_ENDPOINT)",
    )
    ap.add_argument(
        "--access-key",
        default=os.environ.get("SEGDETE_S3_ACCESS_KEY", ""),
        help="S3 access key (env: SEGDETE_S3_ACCESS_KEY)",
    )
    ap.add_argument(
        "--secret-key",
        default=os.environ.get("SEGDETE_S3_SECRET_KEY", ""),
        help="S3 secret key (env: SEGDETE_S3_SECRET_KEY)",
    )
    ap.add_argument(
        "--bucket",
        default=os.environ.get("SEGDETE_S3_BUCKET", "segdete"),
        help="S3 bucket (env: SEGDETE_S3_BUCKET)",
    )
    ap.add_argument(
        "--out-prefix",
        default=os.environ.get("SEGDETE_S3_IN_PREFIX", "in"),
        help="S3 key prefix for uploaded files (env: SEGDETE_S3_IN_PREFIX)",
    )
    ap.add_argument(
        "--region",
        default=os.environ.get("SEGDETE_S3_REGION", "garage"),
        help="S3 region (env: SEGDETE_S3_REGION; garage requires 'garage')",
    )
    args = ap.parse_args()

    if not args.access_key or not args.secret_key:
        raise SystemExit(
            "S3 access/secret key not set (use --access-key/--secret-key or "
            "the SEGDETE_S3_ACCESS_KEY / SEGDETE_S3_SECRET_KEY env vars)"
        )

    source = args.source.rstrip("/")
    key_prefix = args.out_prefix.rstrip("/")

    names = [n for n in _index_files(source) if n.startswith(args.image_prefix)]
    if not names:
        raise SystemExit(
            f"no files with prefix {args.image_prefix!r} in {source}"
        )

    total_size = 0
    for name in names:
        try:
            total_size += _head_size(f"{source}/{name}")
        except urllib.error.URLError:
            pass
    logger.info("found %d files (prefix=%r) (~%.2f GB) -> s3://%s/%s",
                len(names), args.image_prefix, total_size / 1e9,
                args.bucket, key_prefix)

    client = _minio(args.endpoint, args.access_key, args.secret_key, args.region)
    bucket = args.bucket

    if args.dry_run:
        to_upload = 0
        to_skip = 0
        for name in names:
            key = f"{key_prefix}/{name}"
            if _existing_size(client, bucket, key) is not None:
                to_skip += 1
                print(f"  skip (already exists): {key}")
            else:
                to_upload += 1
                print(f"  would upload: {key}")
        print(f"summary: {to_upload} would upload, {to_skip} already exist")
        return

    try:
        uploaded = _upload(client, bucket, key_prefix, source, names, args.retries)
    except Exception as exc:
        logger.error("aborted after error: %s", exc)
        sys.exit(1)

    if not _verify(client, bucket, key_prefix, uploaded):
        sys.exit(1)


if __name__ == "__main__":
    main()