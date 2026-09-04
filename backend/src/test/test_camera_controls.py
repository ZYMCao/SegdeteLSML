import threading
from unittest.mock import Mock

import pytest
from segdete.camera import basler
from segdete.camera.basler import ThreadSafeCameraManager


@pytest.mark.parametrize(
    ("setter", "feature", "auto_feature", "requested", "expected"),
    [
        ("set_exp", "ExposureTime", "ExposureAuto", 500, 500),
        ("set_exp", "ExposureTime", "ExposureAuto", 5000, 1000),
        ("set_gain", "Gain", "GainAuto", 500, 500),
    ],
)
def test_camera_control_can_read_limits_while_holding_access_lock(
    monkeypatch, setter, feature, auto_feature, requested, expected
):
    monkeypatch.setattr(ThreadSafeCameraManager, "_initialize", lambda _: None)
    manager = ThreadSafeCameraManager(sn_list=["test-camera"])
    device = Mock()
    node = getattr(device, feature)
    node.GetMin.return_value = 10
    node.GetMax.return_value = 1000
    manager._camera.cameras = [device]
    results = []
    worker = threading.Thread(
        target=lambda: results.append(getattr(manager, setter)(0, requested)),
        daemon=True,
    )

    worker.start()
    worker.join(timeout=0.5)

    assert not worker.is_alive(), "Camera control deadlocked while reading limits"
    assert results == [True]
    getattr(device, auto_feature).SetValue.assert_called_once_with("Off")
    node.SetValue.assert_called_once_with(expected)


def test_camera_manager_requires_every_configured_camera(monkeypatch):
    backend = Mock(cameras=[Mock(), None])
    backend.initialize.return_value = False
    monkeypatch.setattr(basler, "MyCameras", Mock(return_value=backend))

    manager = ThreadSafeCameraManager(sn_list=["left", "right"])

    assert manager.is_available() is False
    backend.start.assert_not_called()


@pytest.mark.parametrize("capture", ["incomplete", "exception"])
def test_capture_failure_keeps_camera_available(monkeypatch, capture):
    cameras = [Mock(), Mock()]
    for camera in cameras:
        camera.IsOpen.return_value = True
    backend = Mock(cameras=cameras)
    backend.initialize.return_value = True
    if capture == "incomplete":
        backend.grab_frames.return_value = [{"sn": "left"}]
    else:
        backend.grab_frames.side_effect = RuntimeError("capture timeout")
    monkeypatch.setattr(basler, "MyCameras", Mock(return_value=backend))
    manager = ThreadSafeCameraManager(sn_list=["left", "right"])

    assert manager.is_available() is True
    if capture == "incomplete":
        assert manager.grab_frames() == [{"sn": "left"}]
    else:
        with pytest.raises(RuntimeError, match="capture timeout"):
            manager.grab_frames()
    assert manager.is_available() is True
