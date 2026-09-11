"""pylon Open hook: emulated cameras serve prepared frame directories."""

import os
import sys
from pathlib import Path

SERIAL_LEFT = "0815-0000"
SERIAL_RIGHT = "0815-0001"
_ENV_BY_SERIAL = {
    SERIAL_LEFT: "PSEUDOCAMERA_LEFT_DIR",
    SERIAL_RIGHT: "PSEUDOCAMERA_RIGHT_DIR",
}

_installed = False
_original_open = None


def _log(message):
    print(f"pseudocamera shim: {message}", file=sys.stderr, flush=True)


def _dir_for_serial(serial):
    env_name = _ENV_BY_SERIAL.get(serial)
    if env_name is None:
        return None
    value = os.environ.get(env_name, "")
    return value or None


def install():
    global _installed, _original_open
    if _installed:
        return False
    import pypylon.pylon as pylon

    _original_open = pylon.InstantCamera.Open

    def open_serving_frames(self, *args, **kwargs):
        result = _original_open(self, *args, **kwargs)
        try:
            info = self.GetDeviceInfo()
            device_class = info.GetDeviceClass()
            serial = info.GetSerialNumber()
        except Exception as e:
            _log(f"cannot read device info after Open: {e}")
            return result
        if device_class != "BaslerCamEmu":
            return result
        directory = _dir_for_serial(serial)
        if directory is None:
            _log(
                f"emulated camera {serial}: no frame directory env set "
                f"({_ENV_BY_SERIAL.get(serial)}); serving default test pattern"
            )
            return result
        path = str(Path(directory).resolve())
        self.TestImageSelector.SetValue("Off")
        self.ImageFileMode.SetValue("On")
        self.ImageFilename.SetValue(path)
        _log(f"camera {serial} now serves frames from {path}")
        return result

    pylon.InstantCamera.Open = open_serving_frames
    _installed = True
    return True
