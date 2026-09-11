import importlib
import sys
import types

import pytest

import pseudocamera.shim as shim_module


class _Node:
    def __init__(self):
        self.values = []

    def SetValue(self, value):
        self.values.append(value)


class _Info:
    def __init__(self, device_class, serial):
        self.device_class = device_class
        self.serial = serial

    def GetDeviceClass(self):
        return self.device_class

    def GetSerialNumber(self):
        return self.serial


class _BaseCamera:
    def __init__(self, info):
        self._info = info
        self.opened = False
        self.TestImageSelector = _Node()
        self.ImageFileMode = _Node()
        self.ImageFilename = _Node()

    def Open(self):
        self.opened = True
        return self

    def GetDeviceInfo(self):
        return self._info


class _FakePylon:
    def __init__(self, shim, module, camera_cls):
        self.shim = shim
        self.module = module
        self.camera_cls = camera_cls


@pytest.fixture
def fake_pylon(monkeypatch):
    shim = importlib.reload(shim_module)

    class Camera(_BaseCamera):
        pass

    parent = types.ModuleType("pypylon")
    module = types.ModuleType("pypylon.pylon")
    module.InstantCamera = Camera
    parent.pylon = module
    monkeypatch.setitem(sys.modules, "pypylon", parent)
    monkeypatch.setitem(sys.modules, "pypylon.pylon", module)
    return _FakePylon(shim, module, Camera)


def test_install_patches_open_and_serves_frames(fake_pylon, tmp_path, monkeypatch):
    left = tmp_path / "left"
    left.mkdir()
    monkeypatch.setenv("PSEUDOCAMERA_LEFT_DIR", str(left))

    assert fake_pylon.shim.install() is True
    assert fake_pylon.module.InstantCamera.Open is not _BaseCamera.Open

    cam = fake_pylon.camera_cls(_Info("BaslerCamEmu", "0815-0000"))
    cam.Open()
    assert cam.opened is True
    assert cam.TestImageSelector.values == ["Off"]
    assert cam.ImageFileMode.values == ["On"]
    assert cam.ImageFilename.values == [str(left.resolve())]


def test_wrapper_ignores_real_cameras(fake_pylon, tmp_path, monkeypatch):
    monkeypatch.setenv("PSEUDOCAMERA_LEFT_DIR", str(tmp_path))
    fake_pylon.shim.install()

    cam = fake_pylon.camera_cls(_Info("BaslerGigE", "12345"))
    cam.Open()
    assert cam.TestImageSelector.values == []
    assert cam.ImageFilename.values == []


def test_wrapper_without_env_keeps_test_pattern(fake_pylon, monkeypatch):
    monkeypatch.delenv("PSEUDOCAMERA_LEFT_DIR", raising=False)
    fake_pylon.shim.install()

    cam = fake_pylon.camera_cls(_Info("BaslerCamEmu", "0815-0000"))
    cam.Open()
    assert cam.ImageFileMode.values == []
    assert cam.ImageFilename.values == []


def test_install_is_idempotent(fake_pylon):
    assert fake_pylon.shim.install() is True
    patched = fake_pylon.module.InstantCamera.Open
    assert fake_pylon.shim.install() is False
    assert fake_pylon.module.InstantCamera.Open is patched
