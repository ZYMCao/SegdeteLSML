import csv
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from segdete.config.settings import load_settings
from segdete.pipeline import processor
from segdete.vision.classifier import MLClassifier
from segdete.vision.yolo import init_yolo_config


@pytest.fixture
def cycle_inputs(monkeypatch, tmp_path):
    settings = load_settings()
    settings.storage.save_root = str(tmp_path)
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(processor, "datetime", Mock(now=lambda: now))
    save_dir = tmp_path / "test-device" / "2026-09-03" / settings.storage.images_dir
    save_dir.mkdir(parents=True)
    left = np.full((24, 32, 3), 30, dtype=np.uint8)
    right = np.full((24, 32, 3), 100, dtype=np.uint8)
    panorama = np.hstack([left, right])
    camera = Mock()
    camera.grab_frames.return_value = [{"bgr": left}, {"bgr": right}]
    camera.get_status.return_value = "grabbing"
    monkeypatch.setattr(
        processor,
        "stitch_pair",
        Mock(
            return_value=(
                panorama,
                {"ok": True},
                {"enabled": False},
                {"enabled": False},
            )
        ),
    )
    return {
        "camera_manager": camera,
        "tb_client": Mock(access_token="test-device"),
        "settings": settings,
        "ml_classifier": Mock(
            predict=Mock(return_value={"pred": 1, "confidence": 1.0})
        ),
        "rectifier": None,
        "stitch_cfg": settings.vision.stitch.to_dict(),
        "calib_cfg": settings.vision.calib.to_dict(),
        "pre_align_cfg": settings.vision.prealign.to_dict(),
        "yolo_cfg": {**settings.vision.yolo.to_dict(), "enabled": False},
        "save_dir": str(save_dir),
        "dbg_dir": None,
        "csv_path": str(tmp_path / "results.csv"),
        "font_path": None,
        "loop_count": 1,
    }


def test_successful_cycle_saves_images_csv_and_telemetry(cycle_inputs):
    assert processor.process_one_cycle(**cycle_inputs) is True

    with Path(cycle_inputs["csv_path"]).open() as source:
        rows = list(csv.reader(source))
    assert len(rows) == 1
    image_name, timestamp, prediction, image_path = rows[0]
    assert (timestamp, prediction) == ("2026-09-03 12:00:00", "1")
    assert Path(image_path).name == image_name
    assert cv2.imread(image_path).shape == (24, 64, 3)
    saved = Path(cycle_inputs["save_dir"])
    assert len(list(saved.glob("cam*.png"))) == 2
    cycle_inputs["tb_client"].send_telemetry.assert_called_once()
    payload = cycle_inputs["tb_client"].send_telemetry.call_args.args[0]
    assert payload["imageId"] == Path(image_name).stem
    assert payload["classResult"] == 1
    assert payload["urlPre"] == cycle_inputs["settings"].storage.image_url(image_path)


def test_cycle_reports_failure_when_mqtt_rejects_telemetry(cycle_inputs):
    cycle_inputs["tb_client"].send_telemetry.return_value = False

    assert processor.process_one_cycle(**cycle_inputs) is False
    cycle_inputs["tb_client"].send_telemetry.assert_called_once()


@pytest.mark.parametrize("reason", ["missing_frames", "failed_stitch"])
def test_incomplete_cycle_does_not_publish_a_result(cycle_inputs, reason):
    if reason == "missing_frames":
        cycle_inputs["camera_manager"].grab_frames.return_value = []
    else:
        processor.stitch_pair.return_value = (None, {"ok": False}, {}, {})

    assert processor.process_one_cycle(**cycle_inputs) is False

    cycle_inputs["tb_client"].send_telemetry.assert_not_called()
    assert not Path(cycle_inputs["csv_path"]).exists()


def test_capture_exception_skips_cycle_without_publishing(cycle_inputs):
    cycle_inputs["camera_manager"].grab_frames.side_effect = RuntimeError(
        "capture timeout"
    )

    assert processor.process_one_cycle(**cycle_inputs) is False
    cycle_inputs["tb_client"].send_telemetry.assert_not_called()


def test_cycle_with_configured_model_weights_on_cpu(cycle_inputs):
    settings = cycle_inputs["settings"]
    cfg = settings.vision.yolo.to_dict()
    model_path = Path(settings.assets.resolve(cfg["classifier_model"]))
    if not model_path.is_file():
        pytest.skip(f"Configured model weights unavailable: {model_path}")
    init_yolo_config({**cfg, "force_cpu": True})
    try:
        cycle_inputs["ml_classifier"] = MLClassifier()
        cycle_inputs["yolo_cfg"] = cfg

        assert processor.process_one_cycle(**cycle_inputs) is True

        payload = cycle_inputs["tb_client"].send_telemetry.call_args.args[0]
        assert payload["yolo"]["run"] is True
        assert payload["yolo"]["state"]["ok"] is True
        assert payload["yolo"]["backend"].startswith("mobilenetv3_5class_")
        assert Path(payload["yolo"]["vis_path"]).is_file()
    finally:
        init_yolo_config({})


def test_cycle_saves_annotated_image_to_url_pre_when_detections_exist(
    cycle_inputs, monkeypatch
):
    cycle_inputs["yolo_cfg"]["enabled"] = True
    detection = {
        "x": 2,
        "y": 2,
        "w": 10,
        "h": 10,
        "confidence": 0.95,
        "class_name": "中度离析",
    }
    monkeypatch.setattr(
        processor,
        "yolo_detect_once",
        Mock(return_value=([detection], None, {"ok": True, "backend": "mock"})),
    )

    assert processor.process_one_cycle(**cycle_inputs) is True

    with Path(cycle_inputs["csv_path"]).open() as source:
        rows = list(csv.reader(source))
    image_name, _, _, image_path = rows[0]

    payload = cycle_inputs["tb_client"].send_telemetry.call_args.args[0]
    expected_url = cycle_inputs["settings"].storage.image_url(image_path)
    assert payload["urlPre"] == expected_url
    assert payload["urlBbox"] == expected_url
    assert payload["imageId"] == Path(image_name).stem

    saved_img = cv2.imread(image_path)
    # The green rectangle drawn by draw_bboxes has color (0, 255, 0) in BGR
    assert np.any(saved_img[:, :, 1] == 255)

