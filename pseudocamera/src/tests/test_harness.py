import numpy as np
import pytest

from pseudocamera.harness import (
    EMU_SERIALS,
    advance_position,
    build_harness_env,
    frames_equal,
    identify_frame,
    resolve_frames_dir,
)


def test_build_harness_env_sets_six_vars(tmp_path):
    frames = tmp_path / "frames"
    (frames / "left").mkdir(parents=True)
    (frames / "right").mkdir()
    env = build_harness_env(frames, camemu=2)
    assert env == {
        "PYLON_CAMEMU": "2",
        "SEGDETE_CAMERA_SNS": "0815-0000,0815-0001",
        "SEGDETE_PIXEL_FORMAT": "RGB8Packed",
        "PSEUDOCAMERA_LEFT_DIR": str((frames / "left").resolve()),
        "PSEUDOCAMERA_RIGHT_DIR": str((frames / "right").resolve()),
        "SEGDETE_LOG_LEVEL": "INFO",
    }
    assert EMU_SERIALS == ("0815-0000", "0815-0001")


def test_frames_equal_is_pixel_exact():
    a = np.zeros((4, 4, 3), dtype=np.uint8)
    b = a.copy()
    b[0, 0, 0] = 1
    assert frames_equal(a, a.copy()) is True
    assert frames_equal(a, b) is False


def test_identify_frame_returns_first_match_or_none():
    expected = [np.zeros((2, 2, 3), np.uint8), np.full((2, 2, 3), 7, np.uint8)]
    assert identify_frame(np.zeros((2, 2, 3), np.uint8), expected) == 0
    assert identify_frame(np.full((2, 2, 3), 7, np.uint8), expected) == 1
    assert identify_frame(np.full((2, 2, 3), 9, np.uint8), expected) is None


def test_advance_position_accepts_forward_skips_rejects_duplicates():
    assert advance_position(None, 5, 16) == 5
    assert advance_position(5, 6, 16) == 6
    assert advance_position(14, 1, 16) == 1
    with pytest.raises(ValueError, match="duplicate"):
        advance_position(5, 5, 16)


def test_resolve_frames_dir_prefers_existing(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    frames = root / "data" / "frames"
    (frames / "left").mkdir(parents=True)
    (frames / "right").mkdir()
    monkeypatch.chdir(root)
    assert resolve_frames_dir("data/frames") == frames
    with pytest.raises(SystemExit, match="no prep frames"):
        resolve_frames_dir(tmp_path / "missing")
