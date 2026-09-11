# pseudocamera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the standalone `pseudocamera` project that masquerades as two Basler cameras via official pylon Camera Emulation, add the minimal config-driven frame-dir injection to segdete, and delete the legacy replay backend.

**Architecture:** `pseudocamera` (own uv project, `.lsml` repo) prepares `frames/left|right` PNG dirs and launches segdete with env overrides; segdete's `configure_camera` injects `TestImageSelector=Off` → `ImageFileMode=On` → `ImageFilename=<dir>` per camera. Acceptance stops at the camera-layer frame contract.

**Tech Stack:** Python >=3.13, uv, numpy, opencv-python-headless, pytest; pypylon + existing backend stack for segdete-side verification.

**Deviations from skill defaults (mandated by approved plan §8):** No git commit steps (commits only on explicit user request).

**Environment notes:** `uv` lives at `/opt/homebrew/bin/uv` and may not be on PATH — prefix it or export PATH in each shell. Backend suite: `uv run --directory backend pytest -q` from the repo root (baseline green). Backend interpreter: `backend/.venv/bin/python`.

---

## File structure (locked)

Create under `pseudocamera/`:
- `pyproject.toml` — hatchling src layout, `pseudocamera` console script, `pythonpath=["src"]` pytest config
- `.gitignore` — `frames/`, `.venv/`
- `README.md`
- `src/pseudocamera/cli.py` — argparse `prep` / `run` / `harness`; `if __name__ == "__main__":` guard
- `src/pseudocamera/prep.py` — `decode_image`, `split_virtual_stereo`, `fit_within`, `prep_side_by_side`, `prep_independent`
- `src/pseudocamera/run.py` — `CAMEMU_SERIALS`, `build_run_env`, `warn_loudly`, `launch`
- `src/pseudocamera/harness.py` — `EMU_SERIALS`, `build_harness_env`, `assert_fresh_segdete`, `frames_equal`, `main`; lazy pypylon/segdete imports only
- `tests/test_prep.py`, `tests/test_run.py`, `tests/test_harness.py`
- `frames/` — generated, gitignored

Modify in `backend/src/segdete/`:
- `config/acquisition.py` — add 2 fields + `camera_params()` key
- `camera/basler.py` — `configure_camera(..., idx=0)` + call-site `idx=i`
- `cli.py`, `pipeline/processor.py` — replay removals

Modify in `backend/src/test/`:
- delete `test_replay_camera.py`; rewrite replay usages in `test_processor_cycle.py`, `test_cli_mqtt_lifecycle.py`, `test_config.py`, `test_camera_lifecycle.py`

Modify at repo root: `.git/info/exclude` (append `/pseudocamera/`).

---

### Task 1: pseudocamera scaffold + packaging

**Files:**
- Create: `pseudocamera/pyproject.toml`
- Create: `pseudocamera/.gitignore`

- [ ] **Step 1: Create directories**

Run: `mkdir -p pseudocamera/src/pseudocamera pseudocamera/tests pseudocamera/frames`
Expected: exit 0, directories exist.

- [ ] **Step 2: Write `pseudocamera/pyproject.toml`**

```toml
[project]
name = "pseudocamera"
version = "0.1.0"
description = "Standalone Basler camera masquerade for SegDete integration testing (no hardware)"
requires-python = ">=3.13"
dependencies = [
    "numpy>=1.23.0",
    "opencv-python-headless>=4.7.0.72",
]

[project.scripts]
pseudocamera = "pseudocamera.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
force-include = { "src/pseudocamera" = "pseudocamera" }

[tool.pytest.ini_options]
pythonpath = ["src"]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
]
```

- [ ] **Step 3: Write `pseudocamera/.gitignore`**

```
.venv/
frames/
__pycache__/
```

- [ ] **Step 4: Sync the venv**

Run: `uv sync --directory pseudocamera`
Expected: `pseudocamera/.venv` created, exit 0.

---

### Task 2: prep.py (split + fit-scale + manifest) with tests

**Files:**
- Create: `pseudocamera/src/pseudocamera/prep.py`
- Create: `pseudocamera/tests/test_prep.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run --directory pseudocamera pytest tests/test_prep.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pseudocamera.prep'`.

- [ ] **Step 3: Write minimal implementation `pseudocamera/src/pseudocamera/prep.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run --directory pseudocamera pytest tests/test_prep.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Produce real frames from field material (repo root)**

Run: `uv run --project pseudocamera python -c "from pseudocamera.prep import prep_side_by_side; prep_side_by_side('data/left', 'pseudocamera/frames')"`
Expected: exit 0. Verify: `ls pseudocamera/frames/left | wc -l` → `16`; `ls pseudocamera/frames/right | wc -l` → `16`; `pseudocamera/frames/manifest.json` exists.

---

### Task 3: cli.py + run.py with tests

**Files:**
- Create: `pseudocamera/src/pseudocamera/run.py`
- Create: `pseudocamera/src/pseudocamera/cli.py`
- Create: `pseudocamera/tests/test_run.py`

- [ ] **Step 1: Write the failing test `pseudocamera/tests/test_run.py`**

```python
from pseudocamera.run import CAMEMU_SERIALS, build_run_env


def test_build_run_env_sets_exactly_five_vars(tmp_path):
    frames = tmp_path / "frames"
    (frames / "left").mkdir(parents=True)
    (frames / "right").mkdir()
    env = build_run_env(frames, camemu=2)
    assert env == {
        "PYLON_CAMEMU": "2",
        "SEGDETE_CAMERA_SNS": ",".join(CAMEMU_SERIALS),
        "SEGDETE_PIXEL_FORMAT": "RGB8Packed",
        "SEGDETE_PSEUDOCAMERA_LEFT_DIR": str((frames / "left").resolve()),
        "SEGDETE_PSEUDOCAMERA_RIGHT_DIR": str((frames / "right").resolve()),
    }
    assert CAMEMU_SERIALS == ("0815-0000", "0815-0001")
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --directory pseudocamera pytest tests/test_run.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pseudocamera.run'`.

- [ ] **Step 3: Write minimal implementation `pseudocamera/src/pseudocamera/run.py`**

```python
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
        "SEGDETE_PSEUDOCAMERA_LEFT_DIR": left,
        "SEGDETE_PSEUDOCAMERA_RIGHT_DIR": right,
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
    completed = subprocess.run(list(command), env=merged)
    return completed.returncode
```

- [ ] **Step 4: Write `pseudocamera/src/pseudocamera/cli.py`**

```python
"""pseudocamera command line interface."""

import argparse
import sys
from pathlib import Path


def build_parser():
    parser = argparse.ArgumentParser(prog="pseudocamera")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prep", help="Prepare frame directories from source material")
    prep.add_argument("source", nargs="?", default=None)
    prep.add_argument("-o", "--out", default="pseudocamera/frames")
    prep.add_argument("--overlap", type=float, default=0.35)
    prep.add_argument("--max-width", type=int, default=1024)
    prep.add_argument("--max-height", type=int, default=1040)
    prep.add_argument("--left", default=None)
    prep.add_argument("--right", default=None)

    run = sub.add_parser("run", help="Launch segdete with pseudocamera environment")
    run.add_argument("--camemu", type=int, default=2)
    run.add_argument("--frames", default="pseudocamera/frames")
    run.add_argument("target", nargs=argparse.REMAINDER)

    harness = sub.add_parser("harness", help="Verify the camera-layer masquerade")
    harness.add_argument("--frames", type=int, default=3)
    harness.add_argument("--frames-dir", default="pseudocamera/frames")
    harness.add_argument("--camemu", type=int, default=2)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "prep":
        from pseudocamera.prep import prep_independent, prep_side_by_side

        if args.left or args.right:
            if not (args.left and args.right):
                raise SystemExit("--left and --right must be given together")
            prep_independent(args.left, args.right, args.out, args.max_width, args.max_height)
        else:
            if not args.source:
                raise SystemExit("prep needs a source directory or --left/--right")
            prep_side_by_side(args.source, args.out, args.overlap, args.max_width, args.max_height)
        return 0
    if args.command == "run":
        from pseudocamera.prep import prep_side_by_side
        from pseudocamera.run import build_run_env, launch, warn_loudly

        frames_dir = Path(args.frames)
        if not (frames_dir / "left").is_dir():
            prep_side_by_side("data/left", frames_dir)
        warn_loudly()
        target = list(args.target)
        if target and target[0] == "--":
            target = target[1:]
        if not target:
            candidate = Path("backend/.venv/bin/cli")
            if not candidate.is_file():
                raise SystemExit("no command given and backend/.venv/bin/cli not found")
            target = [str(candidate), "--no-web"]
        return launch(target, build_run_env(frames_dir, args.camemu))
    if args.command == "harness":
        from pseudocamera.harness import main as harness_main

        return harness_main(frames=args.frames, frames_dir=args.frames_dir, camemu=args.camemu)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
```

Note: default paths (`pseudocamera/frames`, `data/left`, `backend/.venv/bin/cli`) are repo-root-relative; document in README that `run`/`prep` defaults assume CWD = repo root.

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run --directory pseudocamera pytest tests/test_run.py -q`
Expected: `1 passed`.

- [ ] **Step 6: Verify `--help` works in pseudocamera's own venv**

Run: `uv run --directory pseudocamera pseudocamera --help`
Expected: usage listing `prep`, `run`, `harness`.

- [ ] **Step 7: Spot-check emulation enumeration through `run` (repo root)**

Run: `uv run --project pseudocamera pseudocamera run -- backend/.venv/bin/python -c "from pypylon import pylon; print(sorted(d.GetSerialNumber() for d in pylon.TlFactory.GetInstance().EnumerateDevices()))"`
Expected stdout: `['0815-0000', '0815-0001']`, exit 0 (stderr warnings about MQTT_TOKEN are expected).

---

### Task 4: segdete config fields + configure_camera hook (additive)

**Files:**
- Modify: `backend/src/segdete/config/acquisition.py`
- Modify: `backend/src/segdete/camera/basler.py`
- Modify: `backend/src/test/test_config.py` (append one test)

- [ ] **Step 1: Write the failing test (append to `test_config.py`)**

```python
def test_pseudocamera_dirs_from_environment(monkeypatch):
    monkeypatch.setenv("SEGDETE_PSEUDOCAMERA_LEFT_DIR", "/srv/pseudo/left")
    monkeypatch.setenv("SEGDETE_PSEUDOCAMERA_RIGHT_DIR", "/srv/pseudo/right")

    cfg = AcquisitionConfig()

    assert cfg.pseudocamera_left_dir == "/srv/pseudo/left"
    assert cfg.pseudocamera_right_dir == "/srv/pseudo/right"
    assert cfg.camera_params()["image_file_dirs"] == [
        "/srv/pseudo/left",
        "/srv/pseudo/right",
    ]
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --directory backend pytest src/test/test_config.py::test_pseudocamera_dirs_from_environment -q`
Expected: FAIL with `AttributeError` (no such field).

- [ ] **Step 3: Add fields + params key to `acquisition.py`**

Old:
```python
    camera_backend: Literal["basler", "replay"] = "basler"
    camera_sns: Annotated[list[str], NoDecode] = []
    replay_source: str = "data/left"
```
New:
```python
    camera_backend: Literal["basler", "replay"] = "basler"
    camera_sns: Annotated[list[str], NoDecode] = []
    replay_source: str = "data/left"
    pseudocamera_left_dir: str = ""
    pseudocamera_right_dir: str = ""
```
(`camera_backend` narrowing and `replay_source` deletion happen in Task 5.)

Old (`camera_params` tail):
```python
            "trigger": {
                "selector": self.trigger_selector,
                "mode": self.trigger_mode,
                "source": self.trigger_source,
            },
        }
```
New:
```python
            "trigger": {
                "selector": self.trigger_selector,
                "mode": self.trigger_mode,
                "source": self.trigger_source,
            },
            "image_file_dirs": [self.pseudocamera_left_dir, self.pseudocamera_right_dir],
        }
```

- [ ] **Step
- [ ] **Step 4: Run test to verify pass**

Run: `uv run --directory backend pytest src/test/test_config.py::test_pseudocamera_dirs_from_environment -q`
Expected: `1 passed`.

- [ ] **Step 5: Add `idx` hook to `configure_camera` in `backend/src/segdete/camera/basler.py`**

Old (line 99):
```python
def configure_camera(cam, params: dict):
```
New:
```python
def configure_camera(cam, params: dict, idx: int = 0):
```

Append after the trigger block (after line 179, end of `configure_camera`):
```python
    dirs = params.get("image_file_dirs") or []
    if 0 <= idx < len(dirs) and dirs[idx]:
        _safe_call(lambda: cam.TestImageSelector.SetValue("Off"))
        _safe_call(lambda: cam.ImageFileMode.SetValue("On"))
        _safe_call(lambda: cam.ImageFilename.SetValue(str(dirs[idx])))
```

Old call site (line 300):
```python
                    if self.camera_params:
                        configure_camera(cam, self.camera_params)
```
New:
```python
                    if self.camera_params:
                        configure_camera(cam, self.camera_params, idx=i)
```

- [ ] **Step 6: Run the full backend suite**

Run: `uv run --directory backend pytest -q`
Expected: all pass, no new failures (baseline is green).

---

### Task 5: replay removal + test sync

**Files:**
- Delete: `backend/src/segdete/camera/replay.py`
- Delete: `backend/src/test/test_replay_camera.py`
- Modify: `backend/src/segdete/cli.py` (remove import line 19 + branch lines 115-127, dedent `else:`)
- Modify: `backend/src/segdete/config/acquisition.py` (Literal narrow + delete `replay_source`)
- Modify: `backend/src/segdete/pipeline/processor.py` (lines 53-60)
- Modify: `backend/src/test/test_processor_cycle.py`, `test_cli_mqtt_lifecycle.py`, `test_config.py`, `test_camera_lifecycle.py`

- [ ] **Step 1: Delete the two replay files**

Run: `rm backend/src/segdete/camera/replay.py backend/src/test/test_replay_camera.py`
Expected: exit 0; `ls backend/src/segdete/camera/` shows only `basler.py`.

- [ ] **Step 2: Remove the replay branch from `cli.py`**

Delete line 19 (`from segdete.camera.replay import ReplayCameraManager`).

Old (lines 115-128):
```python
    if settings.acquisition.camera_backend == "replay":
        settings.runtime.prewarm_frames = 0
        settings.vision.prealign.enabled = False
        settings.vision.calib.enabled = False
        settings.vision.stitch.input = "raw"
        settings.vision.stitch.exposure_match = False
        settings.vision.stitch.reuse_prev_on_fail = False
        camera_manager = ReplayCameraManager(settings.acquisition.replay_source)
        logging.warning(
            "Replay camera ready; processing %d image(s) from %s",
            camera_manager.image_count,
            camera_manager.source_dir,
        )
    else:
```
New: delete the whole block (the basler path below becomes the only path; dedent its body one level to match). The surviving code starts with the posix/root warning and the retry loop.

- [ ] **Step 3: Narrow config in `acquisition.py`**

Old:
```python
    camera_backend: Literal["basler", "replay"] = "basler"
    camera_sns: Annotated[list[str], NoDecode] = []
    replay_source: str = "data/left"
    pseudocamera_left_dir: str = ""
    pseudocamera_right_dir: str = ""
```
New:
```python
    camera_backend: Literal["basler"] = "basler"
    camera_sns: Annotated[list[str], NoDecode] = []
    pseudocamera_left_dir: str = ""
    pseudocamera_right_dir: str = ""
```

- [ ] **Step 4: Simplify the empty-capture branch in `processor.py`**

Old (lines 53-60):
```python
    if not frames or len(frames) < 2:
        log = (
            logging.debug
            if getattr(camera_manager, "empty_capture_is_normal", False)
            else logging.warning
        )
        log("⚠️ 抓图不足两帧，等待中...")
        return False
```
New:
```python
    if not frames or len(frames) < 2:
        logging.warning("⚠️ 抓图不足两帧，等待中...")
        return False
```

- [ ] **Step 5: Sync the four test files**

(a) `test_processor_cycle.py`: delete line 9 (`from segdete.camera.replay import ReplayCameraManager`) and delete `test_replay_source_image_flows_to_business_telemetry` (lines 81-92) in full. The `cycle_inputs` fixture already uses a `Mock()` camera manager, so no replacement is needed.

(b) `test_cli_mqtt_lifecycle.py`: replace `test_replay_backend_is_owned_by_running_cli` (lines 48-94) with:

```python
def test_basler_backend_is_owned_by_running_cli(monkeypatch):
    monkeypatch.setenv("MQTT_TOKEN", "test-device")
    settings = load_settings()
    settings.acquisition.camera_sns = ["SN-A", "SN-B"]
    basler_camera = Mock(sn_list=["SN-A", "SN-B"], web_running=True)
    basler_camera.is_available.return_value = True
    client = Mock(access_token="test-device")
    client.connect.return_value = True

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "parse_arguments",
        lambda: SimpleNamespace(
            no_web=True,
            web_fps=None,
            web_save_dir=None,
            host=None,
            port=None,
        ),
    )
    monkeypatch.setattr(cli, "setup_logging", Mock())
    monkeypatch.setattr(cli, "_print_startup_diagnostics", Mock())
    monkeypatch.setattr(cli, "init_yolo_config", Mock())
    basler_factory = Mock(return_value=basler_camera)
    monkeypatch.setattr(cli, "ThreadSafeCameraManager", basler_factory)
    monkeypatch.setattr(cli, "TBEdgeClient", Mock(return_value=client))
    monkeypatch.setattr(cli, "segdete_processing_loop", Mock())
    monkeypatch.setattr(cli.signal, "signal", Mock())

    cli.main()

    basler_factory.assert_called_once_with(
        sn_list=["SN-A", "SN-B"],
        exposure_time=settings.acquisition.exposure_time,
        frame_rate=settings.acquisition.frame_rate,
        camera_params=settings.acquisition.camera_params(),
    )
    client.connect.assert_called_once_with()
```

(c) `test_config.py`: replace `test_replay_camera_config_from_environment` (lines 70-77) — already superseded by the Task 4 test; delete it. Keep `test_replay_camera_rejects_invalid_backend` as-is (still passes under `Literal["basler"]`).

(d) `test_camera_lifecycle.py`: replace `test_camera_is_available_delegates` body (lines 172-182) with:

```python
def test_camera_is_available_delegates():
    from segdete.pipeline.processor import _camera_is_available

    class _StubWithoutHealth:
        sn_list: ClassVar = ["x"]

    with pytest.raises(AttributeError):
        _camera_is_available(_StubWithoutHealth())
```

Also delete `import cv2` (line 6) and `import numpy as np` (line 7) from that file — their only use was line 178 in the deleted block. (`ClassVar`, `pytest` imports stay.)

- [ ] **Step 6: Prove the coupling is gone**

Run: `grep -rn "ReplayCamera\|replay_source\|empty_capture_is_normal" backend/src --include='*.py' | grep -v ".venv"`
Expected: no output.

Run: `grep -rn "split_virtual_stereo\|0\.35" backend/src --include='*.py' | grep -v ".venv"`
Expected: no output.

- [ ] **Step 7: Run the full backend suite**

Run: `uv run --directory backend pytest -q`
Expected: all pass.

---

### Task 6: refresh the backend install

**Files:** none (command only — the `.venv` wheel is a stale Sep-4 snapshot containing `replay.py`).

- [ ] **Step 1: Sync**

Run: `uv sync --directory backend`
Expected: exit 0.

- [ ] **Step 2: Verify the wheel converged**

Run: `ls backend/.venv/lib/python3.13/site-packages/segdete/camera/`
Expected: `basler.py` only (no `replay.py`).

Run: `backend/.venv/bin/python -c "from segdete.config.acquisition import AcquisitionConfig; print('pseudocamera_left_dir' in AcquisitionConfig.model_fields)"`
Expected: `True`.

---

### Task 7: harness.py (camera-layer acceptance) with tests

**Files:**
- Create: `pseudocamera/src/pseudocamera/harness.py`
- Create: `pseudocamera/tests/test_harness.py`

- [ ] **Step 1: Write the failing tests**

```python
import sys
import types

import numpy as np
import pytest

from pseudocamera.harness import (
    EMU_SERIALS,
    assert_fresh_segdete,
    build_harness_env,
    frames_equal,
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
        "SEGDETE_PSEUDOCAMERA_LEFT_DIR": str((frames / "left").resolve()),
        "SEGDETE_PSEUDOCAMERA_RIGHT_DIR": str((frames / "right").resolve()),
        "SEGDETE_LOG_LEVEL": "INFO",
    }
    assert EMU_SERIALS == ("0815-0000", "0815-0001")


def test_frames_equal_is_pixel_exact():
    a = np.zeros((4, 4, 3), dtype=np.uint8)
    b = a.copy()
    b[0, 0, 0] = 1
    assert frames_equal(a, a.copy()) is True
    assert frames_equal(a, b) is False


def test_assert_fresh_segdete_passes_and_fails(monkeypatch):
    module = types.ModuleType("segdete.config.acquisition")

    class Fresh:
        model_fields = {"pseudocamera_left_dir": object()}

    class Stale:
        model_fields = {}

    module.AcquisitionConfig = Fresh
    monkeypatch.setitem(sys.modules, "segdete.config.acquisition", module)
    assert_fresh_segdete()

    module.AcquisitionConfig = Stale
    monkeypatch.setitem(sys.modules, "segdete.config.acquisition", module)
    with pytest.raises(SystemExit, match="uv sync"):
        assert_fresh_segdete()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run --directory pseudocamera pytest tests/test_harness.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pseudocamera.harness'`.

- [ ] **Step 3: Write minimal implementation `pseudocamera/src/pseudocamera/harness.py`**

No module-level `pypylon`/`segdete` imports — all deferred below the env setup so `pseudocamera --help` works in pseudocamera's own venv.

```python
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
        "SEGDETE_PSEUDOCAMERA_LEFT_DIR": left,
        "SEGDETE_PSEUDOCAMERA_RIGHT_DIR": right,
        "SEGDETE_LOG_LEVEL": "INFO",
    }


def assert_fresh_segdete():
    from segdete.config.acquisition import AcquisitionConfig

    if "pseudocamera_left_dir" not in AcquisitionConfig.model_fields:
        raise SystemExit(
            "stale segdete install: AcquisitionConfig lacks pseudocamera_left_dir; "
            "run `uv sync` in backend/ and retry"
        )


def frames_equal(grabbed, expected):
    return bool(np.array_equal(grabbed, expected))


def main(frames=3, frames_dir="pseudocamera/frames", camemu=2):
    frames_dir = Path(frames_dir).resolve()
    os.environ.update(build_harness_env(frames_dir, camemu))
    assert_fresh_segdete()

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
        total = frames * len(left_files)
        for i in range(total):
            grabbed = manager.grab_frames()
            if len(grabbed) != 2:
                raise SystemExit(f"grab {i}: expected 2 frames, got {len(grabbed)}")
            if [f["sn"] for f in grabbed] != list(EMU_SERIALS):
                raise SystemExit(f"grab {i}: bad sn contract: {[f['sn'] for f in grabbed]}")
            expected_left = cv2.imread(str(left_files[i % len(left_files)]))
            expected_right = cv2.imread(str(right_files[i % len(right_files)]))
            if not frames_equal(grabbed[0]["bgr"], expected_left):
                raise SystemExit(f"grab {i}: left frame differs from prep output")
            if not frames_equal(grabbed[1]["bgr"], expected_right):
                raise SystemExit(f"grab {i}: right frame differs from prep output")
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
```

Note: `cli.py` already dispatches `harness` to this `main`; it takes `frames`/`frames_dir`/`camemu` kwargs.

**Implementation note (2026-09-10, behavior-preserving refinement).**
Probing showed two facts that the exact-index comparison in Step 3 did not
account for: (a) freerun `LatestImageOnly` delivery can skip buffers when the
consumer loop lags a 30 fps period — identical to real-camera behavior;
(b) two field photos (`9721776225531.jpg`, `9721776225531_.pic_hd.jpg`) are
byte-identical, so frames 0013/0015 are interchangeable by content
(verified: triggered OneByOne acquisition serves a clean lexicographic
cycle). The harness therefore preloads expected frames once and matches
each grab by membership + forward cyclic order (`identify_frame` /
`advance_position`), which fails loud on any silent fallback, cropping, or
reorder while tolerating delivery skips. The acceptance criterion
(pixel-equal frames in cyclic order) is unchanged.

- [ ] **Step 4: Run unit tests to verify pass**

Run: `uv run --directory pseudocamera pytest -q`
Expected: all pass (`test_prep.py` + `test_run.py` + `test_harness.py`).

- [ ] **Step 5: Acceptance run (repo root, backend interpreter)**

Run: `cd pseudocamera && PYTHONPATH=src:../backend/src ../backend/.venv/bin/python -m pseudocamera.cli harness --frames 3`
Expected: exit 0; log contains `pylon found 2 device(s): ['0815-0000', '0815-0001']`; 48 `grab i:` lines (`3 × 16` left frames); no `SystemExit` text.

---

### Task 8: excludes + README + final acceptance

**Files:**
- Modify: `.git/info/exclude` (append `/pseudocamera/`)
- Create: `pseudocamera/README.md`

- [ ] **Step 1: Exclude pseudocamera from the `.git` repo**

Append one line `/pseudocamera/` to `.git/info/exclude`. Do not touch `.lsml/info/exclude`.

Verify: `git status --short pseudocamera | head -3`
Expected: no output (ignored by `.git`).

Verify: `git lsml status --short pseudocamera | head -3`
Expected: shows `?? pseudocamera/` (visible to `.lsml`, not yet added — no commit per plan §8).

- [ ] **Step 2: Write `pseudocamera/README.md`**

Content (concise runbook):
- What this is: standalone Basler masquerade for SegDete, no hardware, no MQTT.
- Prereqs: `uv` (`/opt/homebrew/bin/uv`, may not be on PATH), backend venv synced (`uv sync --directory backend`).
- Flow: `pseudocamera prep data/left -o pseudocamera/frames` →
  `pseudocamera run [-- command]` (needs `MQTT_TOKEN`; without a broker the segdete CLI blocks at TB Edge connect — see F7) →
  broker-free camera-layer check: `cd pseudocamera && PYTHONPATH=src:../backend/src ../backend/.venv/bin/python -m pseudocamera.cli harness --frames 3`.
- Notes: macOS PNG works though unlisted in Basler docs; `PYLON_CAMEMU` is read at device enumeration (set early anyway); frames cycle by filename order; `grep ReplayCamera` cleanliness refers to the source tree (full convergence via `uv sync`).

- [ ] **Step 3: Run the final acceptance checklist**

Run each, all must hold:
1. `cd pseudocamera && PYTHONPATH=src:../backend/src ../backend/.venv/bin/python -m pseudocamera.cli harness --frames 3` → exit 0, 48 cyclic grabs, pixel-equal frames.
2. With the 6 harness env vars unset: `uv run --directory backend pytest -q` → all pass.
3. `grep -rn "ReplayCamera\|replay_source\|empty_capture_is_normal" backend/src --include='*.py' | grep -v ".venv"` → empty.
4. `grep -rn "split_virtual_stereo" backend/src --include='*.py' | grep -v ".venv"` → empty; `uv run --directory pseudocamera pytest -q` → all pass.
5. `git diff --name-only` (both repos) shows no `mqtt/`, `tb_client`, or rulechain files touched; `grep -n "segdete.pipeline" pseudocamera/src/pseudocamera/harness.py` → empty.

---

## Self-review

**Superseded by v4 (2026-09-10, reviewer round 4 APPROVED).** The user ruled that
everything not necessary vs the pre-replay baseline `4e90ce2` must be rolled back.
Final state, all verified by command output:

- `cli.py` restored byte-identical to `4e90ce2` (`git checkout 4e90ce2 --`,
  diff empty; `git log` shows only replay commits touched it after the baseline).
- `acquisition.py` vs `4e90ce2` = exactly: `+image_file_left_dir` /
  `+image_file_right_dir` fields, `+image_file_dirs` line in `camera_params()`.
  `camera_backend` field, `Literal` import, and the deploy
  `SEGDETE_CAMERA_BACKEND=basler` line are deleted (BaseConfig `extra="ignore"`
  makes deletion behavior-safe; deploy is .git-tracked).
- `configure_camera` keeps the pre-replay signature `(cam, params)`; the 6-line
  injection lives inside `MyCameras.initialize()`'s per-camera loop right after
  the `configure_camera(cam, self.camera_params)` call
  (`_try_set_enum` for the two enums, `_safe_call` for the string). `idx` gone.
- `processor.py`: no action (replay-related diff vs baseline already zero).
- `grep -rn pseudocamera backend/src --include='*.py'` and
  `grep -rn camera_backend backend/src --include='*.py'` → zero hits.
- pseudocamera-side rename sites (reviewer-located): `run.py:18-19`,
  `harness.py:20-21`, `harness.py:29-31` (fail-loud key + message →
  `image_file_left_dir`), `tests/test_run.py:13-14`, `tests/test_harness.py:27-28`
  and `:61`. All applied.
- Verification: backend `108 passed`; pseudocamera `12 passed`; harness
  acceptance exit 0 with 48 pixel-faithful cyclic grabs and
  `pylon found 2 device(s): ['0815-0000', '0815-0001']`.
- The original task list below (T1-T8) documents how the code was built; the
  v4 deltas above supersede the naming/signature details it contains.

## Self-review (v1, superseded by v4 note above)

**1. Spec coverage.** Spec §3 prep → Task 2 (split math, INTER_AREA, manifest, independent dirs) ✓. run → Task 3 (5 env vars, auto-prep, default command, 3 warnings) ✓. harness → Task 7 (6 vars, lazy imports, model_fields fail-loud, enumerate assertion, per-cli.py manager args, cyclic pixel fidelity, stop/close, no pipeline import) ✓; launch contract → Task 7 Step 5 canonical command ✓. Spec §4 additions → Task 4 (fields, params key, hook, idx=i) ✓. Spec §4 deletions → Task 5 (all 5 file groups + line refs) ✓. uv sync → Task 6 ✓. excludes → Task 8 ✓. Acceptance 1-5 → Task 8 Step 3 ✓. Reviewer round-3 remarks → folded (model_fields, source-tree grep note, `__main__` guard, T3 check under backend interpreter) ✓. F7 MQTT warnings → run.py `warn_loudly` + README ✓.

**2. Placeholder scan.** No TBD/TODO/later/appropriate-validation phrasing. Every code step shows the code; every command shows expected output. The only judgment call left to the implementer is none — even the `_StubWithoutHealth` rewrite and unused-import cleanup are spelled out.

**3. Type consistency.** `prep_side_by_side(source, out, overlap, max_w, max_h)` positional order matches cli.py call `prep_side_by_side(args.source, args.out, args.overlap, args.max_width, args.max_height)` ✓ and Task 2 Step 5 keyword form ✓. `prep_independent(left, right, out, max_w, max_h)` matches both call sites ✓. `build_run_env(frames_dir, camemu)` 5 keys; `build_harness_env` 6 keys ✓. `harness.main(frames, frames_dir, camemu)` matches cli.py dispatch kwargs ✓. `configure_camera(cam, params, idx)` call `configure_camera(cam, self.camera_params, idx=i)` ✓. `EMU_SERIALS`/`CAMEMU_SERIALS` both `("0815-0000", "0815-0001")` ✓.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-10-pseudocamera.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
---

## v5 终态（2026-09-10，Round 6 APPROVED）

用户质疑 basler.py 注入块的完全必要性 → v5 将伪装机制整体移出 segdete：

- segdete `cli.py`/`processor.py`/`acquisition.py` 对 4e90ce2 零 diff；
  `basler.py` 对 HEAD 零 diff；masquerade/replay token 在 backend/src 零命中。
- pseudocamera 新增 `shim.py`（patch `pypylon.pylon.InstantCamera.Open`，
  按 emu 序列号注入帧目录三件套）与 `launcher.py`（显式 shim→segdete.cli 链）；
  `run.py` 默认目标改为 `backend/.venv/bin/python -m pseudocamera.launcher --no-web`
  并前置 `pseudocamera/src` 到 PYTHONPATH；env 改为 `PSEUDOCAMERA_LEFT_DIR/RIGHT_DIR`。
- `harness.py` 删除 `assert_fresh_segdete`，fail-loud 由帧保真断言独立承担。
- pyproject 补 `[tool.uv] cache-keys`（修复 console script 陈旧 wheel 陷阱）。
- 验证：backend 107 passed；pseudocamera 16 passed；harness exit 0（48 抓帧
  逐像素 + 循环序 + shim 激活日志）；launcher `--help` 链走通。

---

## v6 调整（2026-09-10，用户裁定）

- 帧产物默认位置：`pseudocamera/frames` → repo 根 **`data/frames`**
  （根 `.gitignore` `/data/` 忽略；避免与 `data/left` 源照片混装）。
- 移除 `run` 的自动 prep（硬编码 `data/left`）→ 缺失时响亮报错。
- 测试保留在 **`pseudocamera/tests/`**（通用惯例；`.lsml` 追踪），不迁 `src/test`。
- 验证：pseudocamera 16 passed；harness 默认路径 exit 0；run 缺失 frames 响亮失败。

---

## v7 调整（2026-09-10，用户裁定）

统一测试布局为 `src/tests`（复数）：`pseudocamera/tests` → `pseudocamera/src/tests`；
`backend/src/test` → `backend/src/tests`；`.git/info/exclude` 同步。
backend 107 passed、pseudocamera 16 passed。此前 v6 的“根级 tests/”决定被本段取代。
