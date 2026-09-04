import cv2
import numpy as np
import pytest
from segdete.camera.replay import ReplayCameraManager


def _write_image(path, image):
    encoded, buffer = cv2.imencode(path.suffix, image)
    assert encoded
    buffer.tofile(path)


def test_replay_camera_reads_source_images_in_order_without_modifying_them(tmp_path):
    image_a = np.zeros((4, 10, 3), dtype=np.uint8)
    image_a[:, :, 0] = np.arange(10)
    image_b = np.full((4, 10, 3), 7, dtype=np.uint8)
    source_b = tmp_path / "b.png"
    source_a = tmp_path / "a.png"
    _write_image(source_b, image_b)
    _write_image(source_a, image_a)
    camera = ReplayCameraManager(tmp_path)

    left, right = camera.grab_frames()

    assert camera.image_count == 2
    assert camera.current_source == "a.png"
    assert left["sn"] == "replay-left"
    assert right["sn"] == "replay-right"
    np.testing.assert_array_equal(left["bgr"], image_a[:, :7])
    np.testing.assert_array_equal(right["bgr"], image_a[:, 3:])
    assert source_a.is_file()
    assert source_b.is_file()

    camera.grab_frames()
    assert camera.current_source == "b.png"
    assert camera.grab_frames() == []


def test_replay_camera_skips_invalid_image_on_next_capture(tmp_path):
    broken = tmp_path / "a-broken.jpg"
    broken.write_bytes(b"not an image")
    valid = tmp_path / "b-valid.png"
    _write_image(valid, np.zeros((4, 10, 3), dtype=np.uint8))
    camera = ReplayCameraManager(tmp_path)

    with pytest.raises(ValueError, match="Unable to decode"):
        camera.grab_frames()

    assert broken.is_file()
    assert len(camera.grab_frames()) == 2


def test_replay_camera_rejects_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        ReplayCameraManager(tmp_path / "missing")


def test_replay_camera_rejects_empty_source(tmp_path):
    with pytest.raises(ValueError, match="No replay images"):
        ReplayCameraManager(tmp_path)
