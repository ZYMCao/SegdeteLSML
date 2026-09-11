"""Side-by-side stereo source preparation for the pseudocamera."""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

_IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png"}


def decode_image(path):
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unable to decode image: {path}")
    return image


def split_virtual_stereo(image, overlap=0.35):
    if image is None or image.ndim != 3 or image.shape[1] < 2:
        raise ValueError("Source image must be a color image at least two pixels wide")
    crop_width = round(image.shape[1] * (1.0 + overlap) / 2.0)
    return (
        image[:, :crop_width].copy(),
        image[:, image.shape[1] - crop_width :].copy(),
    )


def fit_within(image, max_width, max_height):
    height, width = image.shape[:2]
    scale = min(max_width / width, max_height / height)
    if scale >= 1.0:
        return image
    return cv2.resize(
        image,
        (round(width * scale), round(height * scale)),
        interpolation=cv2.INTER_AREA,
    )


def _collect(source_dir):
    sources = sorted(
        path
        for path in Path(source_dir).iterdir()
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )
    if not sources:
        raise ValueError(f"No source images found in: {source_dir}")
    return sources


def _write_frame(path, image):
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"Unable to encode frame: {path}")
    data = buffer.tobytes()
    path.write_bytes(data)
    return hashlib.md5(data).hexdigest()


def _write_manifest(out_dir, mode, overlap, max_width, max_height, entries):
    (Path(out_dir) / "manifest.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "overlap": overlap,
                "target": {"max_width": max_width, "max_height": max_height},
                "frames": entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _entry(source, side, path, image, md5):
    return {
        "source": source,
        "side": side,
        "path": path,
        "size": [int(image.shape[0]), int(image.shape[1])],
        "md5": md5,
    }


def prep_side_by_side(source_dir, out_dir, overlap=0.35, max_width=1024, max_height=1040):
    sources = _collect(source_dir)
    out_dir = Path(out_dir)
    left_dir = out_dir / "left"
    right_dir = out_dir / "right"
    left_dir.mkdir(parents=True, exist_ok=True)
    right_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, source in enumerate(sources):
        left, right = split_virtual_stereo(decode_image(source), overlap=overlap)
        left = fit_within(left, max_width, max_height)
        right = fit_within(right, max_width, max_height)
        name = f"frame_{index:04d}.png"
        left_md5 = _write_frame(left_dir / name, left)
        right_md5 = _write_frame(right_dir / name, right)
        entries.append(_entry(source.name, "left", f"left/{name}", left, left_md5))
        entries.append(_entry(source.name, "right", f"right/{name}", right, right_md5))
    _write_manifest(out_dir, "side-by-side", overlap, max_width, max_height, entries)
    return out_dir


def prep_independent(left_dir, right_dir, out_dir, max_width=1024, max_height=1040):
    out_dir = Path(out_dir)
    entries = []
    for side, source_dir in (("left", left_dir), ("right", right_dir)):
        side_dir = out_dir / side
        side_dir.mkdir(parents=True, exist_ok=True)
        for index, source in enumerate(_collect(source_dir)):
            frame = fit_within(decode_image(source), max_width, max_height)
            name = f"frame_{index:04d}.png"
            md5 = _write_frame(side_dir / name, frame)
            entries.append(_entry(source.name, side, f"{side}/{name}", frame, md5))
    _write_manifest(out_dir, "independent", 0.0, max_width, max_height, entries)
    return out_dir
