from types import SimpleNamespace
from unittest.mock import Mock

from segdete import cli
from segdete.config.settings import load_settings


def test_camera_initialization_failure_never_connects_mqtt(monkeypatch):
    monkeypatch.setenv("MQTT_TOKEN", "test-device")
    settings = load_settings()
    settings.runtime.max_camera_retries = 1
    failed_camera = Mock(sn_list=settings.acquisition.camera_sns, web_running=True)
    failed_camera.is_available.return_value = False
    degraded_camera = Mock(sn_list=[], web_running=True)
    degraded_camera.is_available.return_value = False
    client = Mock(access_token="test-device")

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
    monkeypatch.setattr(
        cli,
        "ThreadSafeCameraManager",
        Mock(side_effect=[failed_camera, degraded_camera]),
    )
    monkeypatch.setattr(cli, "TBEdgeClient", Mock(return_value=client))
    monkeypatch.setattr(cli, "segdete_processing_loop", Mock())
    monkeypatch.setattr(cli.signal, "signal", Mock())

    cli.main()

    client.connect.assert_not_called()
    client.disconnect.assert_called_once_with()


def test_replay_backend_is_owned_by_running_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("MQTT_TOKEN", "test-device")
    settings = load_settings()
    settings.acquisition.camera_backend = "replay"
    settings.runtime.prewarm_frames = 20
    replay_camera = Mock(
        sn_list=["replay-left", "replay-right"],
        inbox=tmp_path / "inbox",
        web_running=True,
    )
    replay_camera.is_available.return_value = True
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
    physical_camera = Mock()
    monkeypatch.setattr(cli, "ThreadSafeCameraManager", physical_camera)
    replay_factory = Mock(return_value=replay_camera)
    monkeypatch.setattr(cli, "ReplayCameraManager", replay_factory)
    monkeypatch.setattr(cli, "TBEdgeClient", Mock(return_value=client))
    monkeypatch.setattr(cli, "segdete_processing_loop", Mock())
    monkeypatch.setattr(cli.signal, "signal", Mock())

    cli.main()

    physical_camera.assert_not_called()
    replay_factory.assert_called_once_with()
    assert settings.runtime.prewarm_frames == 0
    assert settings.vision.prealign.enabled is False
    assert settings.vision.calib.enabled is False
    assert settings.vision.stitch.input == "raw"
    client.connect.assert_called_once_with()
    client.disconnect.assert_called_once_with()
