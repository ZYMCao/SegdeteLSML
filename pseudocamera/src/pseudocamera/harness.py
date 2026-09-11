"""Camera-layer acceptance: prove the emulation masquerade end to end."""

import os
import sys
from pathlib import Path

import cv2
import numpy as np

EMU_SERIALS = ("0815-0000", "0815-0001")


def build_harness_env(frames_dir, camemu=2):
    left = str((Path(frames_dir) / "left").resolve())
    right = str((Path(frames_dir) / "right").resolve())
    return {
        "PYLON_CAMEMU": str(camemu),
        "SEGDETE_CAMERA_SNS": ",".join(EMU_SERIALS),
        "SEGDETE_PIXEL_FORMAT": "RGB8Packed",
        "PSEUDOCAMERA_LEFT_DIR": left,
        "PSEUDOCAMERA_RIGHT_DIR": right,
        "SEGDETE_LOG_LEVEL": "INFO",
    }


def frames_equal(grabbed, expected):
    return bool(np.array_equal(grabbed, expected))


def identify_frame(bgr, expected):
    for index, candidate in enumerate(expected):
        if frames_equal(bgr, candidate):
            return index
    return None


def advance_position(pos, file_index, count):
    if pos is not None and (file_index - pos) % count == 0:
        raise ValueError(f"duplicate frame {file_index}")
    return file_index


def resolve_frames_dir(frames_dir):
    candidate = Path(frames_dir)
    if (candidate / "left").is_dir() and (candidate / "right").is_dir():
        return candidate.resolve()
    alt = Path(candidate.name)
    if (alt / "left").is_dir() and (alt / "right").is_dir():
        return alt.resolve()
    raise SystemExit(f"no prep frames under {candidate.resolve()} (also tried {alt.resolve()})")


def main(frames=3, frames_dir="data/frames", camemu=2):
    frames_dir = resolve_frames_dir(frames_dir)
    os.environ.update(build_harness_env(frames_dir, camemu))

    from pseudocamera import shim

    shim.install()

    from pypylon import pylon
    from segdete.camera.basler import ThreadSafeCameraManager
    from segdete.config.settings import load_settings

    serials = {
        device.GetSerialNumber()
        for device in pylon.TlFactory.GetInstance().EnumerateDevices()
    }
    missing = [sn for sn in EMU_SERIALS if sn not in serials]
    if missing:
        raise SystemExit(f"emulation devices missing: {missing} (seen: {sorted(serials)})")

    settings = load_settings()
    manager = ThreadSafeCameraManager(
        sn_list=settings.acquisition.camera_sns,
        exposure_time=settings.acquisition.exposure_time,
        frame_rate=settings.acquisition.frame_rate,
        camera_params=settings.acquisition.camera_params(),
    )
    if not manager.is_available():
        raise SystemExit("camera manager unavailable after init")
    left_files = sorted((frames_dir / "left").glob("frame_*.png"))
    right_files = sorted((frames_dir / "right").glob("frame_*.png"))
    if not left_files or not right_files:
        raise SystemExit(f"no prep frames under {frames_dir}")

    manager.start()
    try:
        expected_left = [cv2.imread(str(path)) for path in left_files]
        expected_right = [cv2.imread(str(path)) for path in right_files]
        pos = [None, None]
        total = frames * len(left_files)
        for i in range(total):
            grabbed = manager.grab_frames()
            if len(grabbed) != 2:
                raise SystemExit(f"grab {i}: expected 2 frames, got {len(grabbed)}")
            if [f["sn"] for f in grabbed] != list(EMU_SERIALS):
                raise SystemExit(f"grab {i}: bad sn contract: {[f['sn'] for f in grabbed]}")
            for side, expected in ((0, expected_left), (1, expected_right)):
                file_index = identify_frame(grabbed[side]["bgr"], expected)
                if file_index is None:
                    raise SystemExit(
                        f"grab {i}: side {side} frame equals no prep frame "
                        f"(shim inactive, silent fallback, or corruption?)"
                    )
                try:
                    pos[side] = advance_position(pos[side], file_index, len(expected))
                except ValueError as e:
                    raise SystemExit(f"grab {i}: side {side} out of cyclic order: {e}")
            print(
                f"grab {i}: left={grabbed[0]['bgr'].shape} "
                f"right={grabbed[1]['bgr'].shape} status={manager.get_status()}",
                flush=True,
            )
    finally:
        manager.stop()
        manager.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
