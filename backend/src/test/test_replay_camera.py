from pathlib import Path

import cv2
import numpy as np
import pytest
import segdete.scripts.replay_camera as replay


@pytest.fixture
def replay_inbox(monkeypatch, tmp_path):
    inbox = tmp_path / "inbox"
    monkeypatch.setattr(replay, "_REPLAY_INBOX", inbox)
    monkeypatch.setattr(replay, "_REPLAY_POLL_TIMEOUT_SEC", 0)
    return inbox


def _write_image(path, image):
    encoded, buffer = cv2.imencode(path.suffix, image)
    assert encoded
    buffer.tofile(path)


def test_producer_atomically_queues_an_unchanged_image(tmp_path, replay_inbox):
    source = tmp_path / "工地.jpg"
    source.write_bytes(b"field-image")

    queued = replay.enqueue_image(source)

    assert queued.parent == replay_inbox
    assert queued.read_bytes() == b"field-image"
    assert not list(replay_inbox.glob("*.part"))


def test_producer_filters_sorts_and_limits_images(tmp_path):
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    _write_image(tmp_path / "b.PNG", image)
    _write_image(tmp_path / "a.jpg", image)
    (tmp_path / "notes.txt").write_text("not an image")

    assert [path.name for path in replay.find_images(tmp_path, limit=1)] == ["a.jpg"]


def test_replay_camera_consumes_queued_image_as_virtual_stereo(
    tmp_path, replay_inbox
):
    image = np.zeros((4, 10, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(10)
    source = tmp_path / "工地.png"
    _write_image(source, image)
    queued = replay.enqueue_image(source)
    camera = replay.ReplayCameraManager()

    left, right = camera.grab_frames()

    assert left["sn"] == "replay-left"
    assert right["sn"] == "replay-right"
    np.testing.assert_array_equal(left["bgr"], image[:, :7])
    np.testing.assert_array_equal(right["bgr"], image[:, 3:])
    assert not queued.exists()
    assert camera.is_available() is True
    assert camera.grab_frames() == []


def test_replay_camera_marks_invalid_image_as_failed(replay_inbox):
    replay_inbox.mkdir(parents=True)
    source = replay_inbox / "broken.jpg"
    source.write_bytes(b"not an image")
    camera = replay.ReplayCameraManager()

    with pytest.raises(ValueError, match="Unable to decode"):
        camera.grab_frames()

    assert not source.exists()
    assert (replay_inbox / "broken.jpg.failed").is_file()


def test_replay_cli_uses_configured_source(monkeypatch):
    monkeypatch.setenv("SEGDETE_REPLAY_SOURCE", "/srv/field-images")

    args = replay.parse_arguments([])

    assert args.input_dir == "/srv/field-images"


def test_replay_cli_rejects_negative_interval():
    with pytest.raises(SystemExit):
        replay.parse_arguments(["--interval", "-1"])


def test_find_images_rejects_empty_directory(tmp_path):
    with pytest.raises(ValueError, match="No supported images"):
        replay.find_images(Path(tmp_path))
