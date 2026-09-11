# pseudocamera

Standalone Basler camera masquerade for SegDete integration testing.
No camera hardware, no MQTT involvement, **zero segdete source changes**.

Two layers:

1. **Emulation devices** — `PYLON_CAMEMU=2` makes pylon provide two
   `BaslerCamEmu` devices (serials `0815-0000`/`0815-0001`). segdete
   enumerates and drives them through its real `camera/basler.py` path.
2. **Frame injection shim** — emulated devices only serve custom frames
   if `TestImageSelector=Off`, `ImageFileMode=On`, `ImageFilename=<dir>`
   are set inside the process. `shim.py` monkeypatches
   `pypylon.pylon.InstantCamera.Open` and applies those three features
   for emulated serials, so segdete stays untouched. Activation and
   failures are logged loudly (`pseudocamera shim: ...` on stderr);
   real cameras and absent env vars are no-ops.

## Prereqs

- `uv` (`/opt/homebrew/bin/uv`; may not be on PATH)
- Each project's own venv synced (`uv sync --directory backend`,
  `uv sync --directory pseudocamera`). Both pyprojects set
  `[tool.uv] cache-keys` on `src/**/*.py`, so source edits rebuild the
  installed wheel automatically on the next `uv run`/`uv sync`.

## Flow

Prepare frame directories from side-by-side stereo photos
(35% overlap split lives here, not in segdete). Output defaults to
`data/frames/` under the repo root (`data/` is gitignored):

```
uv run --directory pseudocamera pseudocamera prep data/left
```

Or normalize two independent directories:

```
uv run --directory pseudocamera pseudocamera prep --left <dir> --right <dir> -o <frames-dir>
```

Launch segdete with the masquerade (shim + env, via the explicit
launcher import chain; needs `MQTT_TOKEN`, and without a reachable
broker the segdete CLI blocks at TB Edge connect before the processing
loop — that is segdete behavior, not this tool). Fails loudly if the
frames dir does not exist; run `prep` first:

```
uv run --project pseudocamera pseudocamera run
```

(default target: `backend/.venv/bin/python -m pseudocamera.launcher
--no-web`; a custom command can follow `--`.)

Broker-free camera-layer verification (the acceptance check), from the
repo root:

```
PYTHONPATH=pseudocamera/src:backend/src backend/.venv/bin/python -m pseudocamera.cli harness --frames 3
```

The harness sets `PYLON_CAMEMU`, `SEGDETE_CAMERA_SNS`,
`SEGDETE_PIXEL_FORMAT`, `PSEUDOCAMERA_LEFT_DIR`,
`PSEUDOCAMERA_RIGHT_DIR`, `SEGDETE_LOG_LEVEL=INFO`, installs the shim,
runs the real `ThreadSafeCameraManager` lifecycle, and asserts every
grabbed frame is pixel-equal to a prep frame and arrives in cyclic
filename order (forward skips tolerated — same as `LatestImageOnly` on
real cameras). A silently inactive shim fails loudly here: default
gradient test frames match no prep frame.

## Notes

- Tests live in `pseudocamera/src/tests/`, unified with the backend's
  `backend/src/tests/` layout, tracked by the `.lsml` repo:
  `uv run --directory pseudocamera pytest`.
- Prepared frames live under repo-root `data/frames/` (gitignored via
  the root `.gitignore` `/data/` entry); nothing is generated inside
  `pseudocamera/`.
- PNG works on macOS though Basler docs only list Windows/Linux formats.
- `PYLON_CAMEMU` is read at device enumeration; set it before first use.
- The shim depends on the Python binding shape of pypylon
  (`InstantCamera.Open`). A major pylon upgrade could change it; the
  harness frame-fidelity assertion is the loud backstop.
- Frame order is the emulation directory cycle; duplicate source photos
  produce duplicate frames (interchangeable by content).
