"""
Upload stitched panoramas to the S3 bucket `segdete` under `in/`.

STRICTLY reuses SegDete business logic — no bespoke computer-vision here.
This tool only:
  * reads left/right pairs from local dirs (data/left + data/right),
  * calls segdete.pipeline.stitch_pair (the SAME function the production
    processor.py uses — one source of truth, changes propagate automatically),
  * uploads the panorama to MinIO object storage in/<date>/<stem>_stitched.jpg.

Nothing here is coupled to cameras, /static-persister, CSV, or MQTT.

S3 configuration: CLI flags take precedence over environment variables
(never hard-code secrets):
  --endpoint    SEGDETE_S3_ENDPOINT   (default favstimacmini.local:3900)
  --access-key  SEGDETE_S3_ACCESS_KEY
  --secret-key  SEGDETE_S3_SECRET_KEY
  --bucket      SEGDETE_S3_BUCKET     (default segdete)
  --in-prefix   SEGDETE_S3_IN_PREFIX  (default in)
  --region      SEGDETE_S3_REGION     (default garage — Garage S3 requires this specific region)
"""

import argparse
import datetime as _dt
import io
import logging
import os

import cv2
import numpy as np
from minio import Minio

from segdete.config.settings import load_settings
from segdete.pipeline.stitch_pair import stitch_pair
from segdete.vision.rectify import StereoRectifier

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")


def _load_bgr(path):
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _encode_jpg(bgr, quality=90):
    ok, buf = cv2.imencode(
        ".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    )
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return buf.tobytes()


def _collect(left_dir, right_dir):
    left = {f for f in os.listdir(left_dir) if f.lower().endswith(_EXT)}
    right = (
        {f for f in os.listdir(right_dir) if f.lower().endswith(_EXT)}
        if os.path.isdir(right_dir)
        else set()
    )
    return sorted(left & right), sorted(left - right)


def _minio(endpoint, access, secret, region, bucket, prefix):
    if not access or not secret:
        raise SystemExit(
            "S3 access/secret key not set (use --access-key/--secret-key or "
            "the SEGDETE_S3_ACCESS_KEY / SEGDETE_S3_SECRET_KEY env vars)"
        )
    client = Minio(
        endpoint,
        access_key=access,
        secret_key=secret,
        secure=False,
        region=region,
    )
    return client, bucket, prefix


def _upload(client, bucket, prefix, stem, pano_bytes):
    date = _dt.date.today().isoformat()
    key = f"{prefix.rstrip('/')}/{date}/{stem}_stitched.jpg"
    client.put_object(
        bucket,
        key,
        io.BytesIO(pano_bytes),
        length=len(pano_bytes),
        content_type="image/jpeg",
    )
    return key


def main():
    ap = argparse.ArgumentParser(
        description="Stitch left/right pairs -> S3 bucket segdete/in/"
    )
    ap.add_argument("--data-dir", default=os.environ.get("SEGDETE_DATA_DIR", "data"),
                    help="root containing left/ and right/ (env: SEGDETE_DATA_DIR, default: data)")
    ap.add_argument("--left-only", action="store_true",
                    help="also upload single left images (no pair) as-is, no stitch")
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
        "--in-prefix",
        default=os.environ.get("SEGDETE_S3_IN_PREFIX", "in"),
        help="S3 key prefix (env: SEGDETE_S3_IN_PREFIX)",
    )
    ap.add_argument(
        "--region",
        default=os.environ.get("SEGDETE_S3_REGION", "garage"),
        help="S3 region (env: SEGDETE_S3_REGION; garage requires 'garage')",
    )
    args = ap.parse_args()

    left_dir = os.path.join(args.data_dir, "left")
    right_dir = os.path.join(args.data_dir, "right")
    if not os.path.isdir(left_dir):
        raise SystemExit(f"left dir not found: {left_dir}")

    pairs, singles = _collect(left_dir, right_dir)
    if not pairs and not (args.left_only and singles):
        raise SystemExit("no matching pairs (and --left-only not set / no singles)")

    settings = load_settings()
    pre_cfg = settings.vision.prealign.to_dict()
    cal_cfg = settings.vision.calib.to_dict()
    st_cfg = settings.vision.stitch.to_dict()
    rectifier = StereoRectifier(cal_cfg)  # reuse undistort/rectify map cache

    client, bucket, prefix = _minio(
        args.endpoint, args.access_key, args.secret_key,
        args.region, args.bucket, args.in_prefix,
    )

    for stem in pairs:
        left = _load_bgr(os.path.join(left_dir, stem))
        right = _load_bgr(os.path.join(right_dir, stem))
        if left is None or right is None:
            logger.warning("skip %s: read failed", stem)
            continue
        pano, st_info, _pa, _ri = stitch_pair(
            left,
            right,
            pre_align_cfg=pre_cfg,
            calib_cfg=cal_cfg,
            stitch_cfg=st_cfg,
            rectifier=rectifier,
        )
        if pano is None:
            logger.warning("skip %s: stitch failed (%s)", stem, st_info)
            continue
        name = os.path.splitext(stem)[0]
        key = _upload(client, bucket, prefix, name, _encode_jpg(pano))
        logger.info("uploaded s3://%s/%s (model=%s ok=%s)",
                    bucket, key, st_info.get("model"), st_info.get("ok"))

    if args.left_only:
        for stem in singles:
            left = _load_bgr(os.path.join(left_dir, stem))
            if left is None:
                logger.warning("skip %s: read failed", stem)
                continue
            name = os.path.splitext(stem)[0]
            key = _upload(client, bucket, prefix, f"{name}_left_only", _encode_jpg(left))
            logger.info("uploaded single-left s3://%s/%s", bucket, key)


if __name__ == "__main__":
    main()
