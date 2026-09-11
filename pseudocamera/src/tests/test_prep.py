import hashlib
import json

import cv2
import numpy as np
import pytest

from pseudocamera.prep import (
    fit_within,
    prep_independent,
    prep_side_by_side,
    split_virtual_stereo,
)


def test_split_virtual_stereo_uses_explicit_overlap():
    image = np.zeros((100, 1000, 3), dtype=np.uint8)
    left, right = split_virtual_stereo(image, overlap=0.35)
    assert left.shape == (100, 675, 3)
    assert right.shape == (100, 675, 3)
    np.testing.assert_array_equal(left[:, 325:], right[:, :350])


def test_split_rejects_non_color_image():
    with pytest.raises(ValueError, match="color image"):
        split_virtual_stereo(np.zeros((10, 10), dtype=np.uint8))


def test_fit_within_downscales_only():
    image = np.zeros((1704, 863, 3), dtype=np.uint8)
    fitted = fit_within(image, 1024, 1040)
    assert fitted.shape[0] <= 1040 and fitted.shape[1] <= 1024
    assert fitted.shape[0] == 1040
    small = np.zeros((100, 100, 3), dtype=np.uint8)
    assert fit_within(small, 1024, 1040) is small


def test_prep_side_by_side_writes_dirs_and_manifest(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for i in range(2):
        image = np.zeros((1704, 1279, 3), dtype=np.uint8)
        image[:, :, 0] = i * 60
        assert cv2.imwrite(str(source / f"photo_{i}.jpg"), image)
    out = tmp_path / "frames"
    prep_side_by_side(source, out, overlap=0.35, max_width=1024, max_height=1040)
    left = sorted((out / "left").glob("frame_*.png"))
    right = sorted((out / "right").glob("frame_*.png"))
    assert [p.name for p in left] == ["frame_0000.png", "frame_0001.png"]
    assert [p.name for p in right] == ["frame_0000.png", "frame_0001.png"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["overlap"] == 0.35
    assert manifest["target"] == {"max_width": 1024, "max_height": 1040}
    assert len(manifest["frames"]) == 4
    for entry in manifest["frames"]:
        digest = hashlib.md5((out / entry["path"]).read_bytes()).hexdigest()
        assert digest == entry["md5"]


def test_prep_independent_normalizes_two_dirs(tmp_path):
    left_src = tmp_path / "l"
    left_src.mkdir()
    right_src = tmp_path / "r"
    right_src.mkdir()
    assert cv2.imwrite(str(left_src / "a.png"), np.zeros((2000, 2000, 3), np.uint8))
    assert cv2.imwrite(str(right_src / "a.png"), np.zeros((100, 100, 3), np.uint8))
    out = tmp_path / "frames"
    prep_independent(left_src, right_src, out)
    assert cv2.imread(str(out / "left" / "frame_0000.png")).shape[0] <= 1040
    assert (out / "right" / "frame_0000.png").is_file()
