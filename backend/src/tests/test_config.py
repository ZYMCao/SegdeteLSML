# -*- coding: utf-8 -*-
"""Tests for domain config defaults and environment overrides."""

import pytest
from pydantic import ValidationError
from segdete.config.acquisition import AcquisitionConfig
from segdete.config.assets import AssetsConfig
from segdete.config.messaging import MessagingConfig
from segdete.config.runtime import RuntimeConfig
from segdete.config.vision.yolo import YoloConfig


def test_yolo_config_defaults():
    expected = {
        "enabled": True,
        "cfg": "yolov4.cfg",
        "weights": "yolov4.weights",
        "names": "coco.names",
        "conf_threshold": 0.25,
        "nms_threshold": 0.45,
        "input_size": 608,
        "force_cpu": False,
        "max_retry": 5,
        "min_conf": 0.05,
        "conf_step": 0.05,
        "classifier_model": "5class_v2_context/best_5class.pth",
        "classifier_window": 768,
        "classifier_stride": 384,
        "classifier_threshold": 0.60,
        "classifier_batch_size": 64,
    }
    assert YoloConfig().to_dict() == expected


def test_yolo_classifier_env_override(monkeypatch):
    monkeypatch.setenv("SEGDETE_YOLO_CLASSIFIER_WINDOW", "512")
    assert YoloConfig().classifier_window == 512


def test_yolo_classifier_model_resolves_through_assets():
    resolved = AssetsConfig().resolve(YoloConfig().classifier_model)
    assert resolved.endswith("yoloassets/5class_v2_context/best_5class.pth")


def test_messaging_config_defaults():
    cfg = MessagingConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 1883
    assert cfg.access_token == ""


def test_messaging_config_env_override(monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "192.168.1.100")
    monkeypatch.setenv("MQTT_PORT", "1884")
    monkeypatch.setenv("MQTT_TOKEN", "my-secret-token")
    cfg = MessagingConfig()
    assert cfg.host == "192.168.1.100"
    assert cfg.port == 1884
    assert cfg.access_token == "my-secret-token"


def test_messaging_config_ignores_legacy_tb_env(monkeypatch):
    monkeypatch.setenv("SEGDETE_TB_HOST", "remote-host")
    monkeypatch.setenv("SEGDETE_TB_TOKEN", "legacy-token")
    cfg = MessagingConfig()
    assert cfg.host == "localhost"
    assert cfg.access_token == ""


@pytest.mark.parametrize("value", [-1, True, 2.0, "1.5", None])
def test_runtime_rejects_invalid_interval(value):
    with pytest.raises(ValidationError):
        RuntimeConfig(interval_sec=value)


@pytest.mark.parametrize("value", ["0", "10"])
def test_runtime_interval_from_environment(monkeypatch, value):
    monkeypatch.setenv("SEGDETE_INTERVAL_SEC", value)
    assert RuntimeConfig().interval_sec == int(value)
