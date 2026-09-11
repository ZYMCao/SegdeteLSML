# -*- coding: utf-8 -*-
"""P0 camera lifecycle tests: no handle leak, Open-failure release, true health."""

from typing import ClassVar

import pytest
from pypylon import pylon

assert hasattr(pylon, "GenericException")

from segdete.camera.basler import ThreadSafeCameraManager

FakePylonError = type("FakePylonError", (pylon.GenericException,), {})


class FakeDevice:
    def __init__(self, sn):
        self._sn = sn

    def GetSerialNumber(self):
        return self._sn


class FakeCam:
    fail_open_sns: ClassVar = frozenset()
    fail_start_exc: ClassVar = None
    removed_sns: ClassVar = frozenset()
    detached_sns: ClassVar = frozenset()
    instances: ClassVar = []

    def __init__(self, device):
        self.sn = device.GetSerialNumber()
        self._open = False
        self._grabbing = False
        self.close_calls = 0
        self.destroy_calls = 0
        FakeCam.instances.append(self)

    def IsOpen(self):
        return self._open

    def IsGrabbing(self):
        return self._grabbing

    def IsPylonDeviceAttached(self):
        return self.sn not in FakeCam.detached_sns

    def IsCameraDeviceRemoved(self):
        return self.sn in FakeCam.removed_sns

    def Open(self):
        if self.sn in FakeCam.fail_open_sns:
            raise FakePylonError(f"open failed: {self.sn}")
        self._open = True

    def Close(self):
        self.close_calls += 1
        self._open = False

    def DestroyDevice(self):
        self.destroy_calls += 1

    def StartGrabbing(self, strategy=None):
        if FakeCam.fail_start_exc is not None:
            raise FakeCam.fail_start_exc
        self._grabbing = True

    def StopGrabbing(self):
        self._grabbing = False


class FakeTlFactory:
    sns: ClassVar = []

    @staticmethod
    def GetInstance():
        return FakeTlFactory()

    def EnumerateDevices(self):
        return [FakeDevice(sn) for sn in FakeTlFactory.sns]

    def CreateDevice(self, dev):
        return dev


@pytest.fixture
def fake_pylon(monkeypatch):
    FakeCam.fail_open_sns = frozenset()
    FakeCam.fail_start_exc = None
    FakeCam.removed_sns = frozenset()
    FakeCam.detached_sns = frozenset()
    FakeCam.instances = []
    FakeTlFactory.sns = ["SN1", "SN2"]
    monkeypatch.setattr(pylon, "TlFactory", FakeTlFactory)
    monkeypatch.setattr(pylon, "InstantCamera", FakeCam)


def _by_sn(sn):
    return next(c for c in FakeCam.instances if c.sn == sn)


def test_start_hardware_fault_no_raise_and_cleaned(fake_pylon):
    FakeCam.fail_start_exc = FakePylonError("transport boom")
    manager = ThreadSafeCameraManager(sn_list=["SN1", "SN2"])
    assert manager.is_available() is False
    for cam in FakeCam.instances:
        assert cam.close_calls >= 1
        assert cam.destroy_calls >= 1


def test_start_programming_fault_reraises_after_cleanup(fake_pylon):
    FakeCam.fail_start_exc = AttributeError("programming boom")
    with pytest.raises(AttributeError):
        ThreadSafeCameraManager(sn_list=["SN1", "SN2"])
    assert FakeCam.instances, "cameras must have been opened before the fault"
    for cam in FakeCam.instances:
        assert cam.close_calls >= 1
        assert cam.destroy_calls >= 1


def test_open_failure_releases_handle(fake_pylon):
    FakeCam.fail_open_sns = frozenset({"SN2"})
    manager = ThreadSafeCameraManager(sn_list=["SN1", "SN2"])
    assert manager.is_available() is False
    bad = _by_sn("SN2")
    assert bad.close_calls >= 1
    assert bad.destroy_calls >= 1
    good = _by_sn("SN1")
    assert good.IsOpen() or good.close_calls >= 1
    manager.close()
    for cam in FakeCam.instances:
        assert cam.close_calls >= 1
        assert cam.destroy_calls >= 1


def test_missing_sn_does_not_crash_initialize(fake_pylon):
    manager = ThreadSafeCameraManager(sn_list=["SN1", "MISSING"])
    assert manager.is_available() is False
    manager.close()


def test_health_detects_removed(fake_pylon):
    manager = ThreadSafeCameraManager(sn_list=["SN1", "SN2"])
    assert manager.is_available() is True
    FakeCam.removed_sns = frozenset({"SN1"})
    assert manager.is_available() is False
    assert "removed" in manager.get_status()
    manager.close()


def test_health_detects_detached(fake_pylon):
    manager = ThreadSafeCameraManager(sn_list=["SN1", "SN2"])
    assert manager.is_available() is True
    FakeCam.detached_sns = frozenset({"SN2"})
    assert manager.is_available() is False
    assert "detached" in manager.get_status()
    manager.close()


def test_cli_contract_no_leak_on_unavailable(fake_pylon):
    FakeCam.fail_open_sns = frozenset({"SN1", "SN2"})
    candidate = ThreadSafeCameraManager(sn_list=["SN1", "SN2"])
    assert candidate.is_available() is False
    candidate.close()
    for cam in FakeCam.instances:
        assert cam.close_calls >= 1
        assert cam.destroy_calls >= 1


def test_camera_is_available_delegates():
    from segdete.pipeline.processor import _camera_is_available

    class _StubWithoutHealth:
        sn_list: ClassVar = ["x"]

    with pytest.raises(AttributeError):
        _camera_is_available(_StubWithoutHealth())
