"""Launch segdete with pseudocamera environment overrides."""

import os
import subprocess
import sys
from pathlib import Path

CAMEMU_SERIALS = ("0815-0000", "0815-0001")


def build_run_env(frames_dir, camemu=2):
    left = str((Path(frames_dir) / "left").resolve())
    right = str((Path(frames_dir) / "right").resolve())
    return {
        "PYLON_CAMEMU": str(camemu),
        "SEGDETE_CAMERA_SNS": ",".join(CAMEMU_SERIALS),
        "SEGDETE_PIXEL_FORMAT": "RGB8Packed",
        "PSEUDOCAMERA_LEFT_DIR": left,
        "PSEUDOCAMERA_RIGHT_DIR": right,
    }


def warn_loudly():
    if "PYLON_CAMEMU" in os.environ:
        print(
            f"WARNING: PYLON_CAMEMU already set to {os.environ['PYLON_CAMEMU']!r}; "
            "it will be overridden.",
            file=sys.stderr,
        )
    if not os.environ.get("MQTT_TOKEN"):
        print(
            "WARNING: MQTT_TOKEN is not set; segdete CLI exits before camera init "
            "without it (cli.py fail-fast).",
            file=sys.stderr,
        )
    print(
        "NOTE: without a reachable MQTT broker the segdete CLI blocks at TB Edge "
        "connect before the processing loop; use `pseudocamera harness` for "
        "broker-free camera-layer verification.",
        file=sys.stderr,
    )


def launch(command, overrides):
    merged = dict(os.environ)
    merged.update(overrides)
    src = str(Path(__file__).resolve().parents[1])
    existing = merged.get("PYTHONPATH", "")
    merged["PYTHONPATH"] = f"{src}:{existing}" if existing else src
    completed = subprocess.run(list(command), env=merged)
    return completed.returncode
