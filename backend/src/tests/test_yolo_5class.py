# -*- coding: utf-8 -*-
"""Adapter contract tests for the 5-class yolo_detect_* entry points."""

import numpy as np
import pytest
import torch
from torch import nn
from torchvision import models

from segdete.vision import yolo as yolo_mod
from segdete.vision.classifier import MLClassifier
from segdete.vision.detector_5class import CLASS_ZH
from segdete.vision.yolo import (
    init_yolo_config,
    yolo_detect_auto_retry,
    yolo_detect_once,
    yolo_detect_sliced,
)


@pytest.fixture(autouse=True)
def _reset_yolo_runtime():
    init_yolo_config({"force_cpu": True})
    yield
    init_yolo_config({})


@pytest.fixture(scope="module")
def tiny_checkpoint(tmp_path_factory):
    model = models.mobilenet_v3_large(weights=None)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, 5)
    ckpt = {"model": model.state_dict(), "classes": CLASS_ZH}
    path = tmp_path_factory.mktemp("ckpt5") / "tiny_model.pth"
    torch.save(ckpt, path)
    return str(path)


def _init_tiny(tiny_checkpoint):
    init_yolo_config(
        {
            "classifier_model": tiny_checkpoint,
            "classifier_window": 768,
            "classifier_stride": 384,
            "classifier_threshold": 0.60,
            "classifier_batch_size": 8,
            "force_cpu": True,
        }
    )


def test_ml_classifier_stub(tiny_checkpoint):
    _init_tiny(tiny_checkpoint)
    classifier = MLClassifier()
    assert yolo_mod._RUNTIME is not None
    result = classifier.predict(np.zeros((100, 100, 3), np.uint8))
    assert result == {"pred": 1, "confidence": 1.0}


def test_init_yolo_config_resets_runtime(monkeypatch):
    init_yolo_config({"force_cpu": True})
    monkeypatch.setattr(yolo_mod, "_RUNTIME", object())
    init_yolo_config({"force_cpu": True})
    assert yolo_mod._RUNTIME is None
    init_yolo_config({"force_cpu": True})
    assert yolo_mod._RUNTIME is None


def test_detect_contract(tiny_checkpoint):
    _init_tiny(tiny_checkpoint)
    img = np.zeros((400, 600, 3), dtype=np.uint8)
    dets, vis, state = yolo_detect_once(img)
    assert isinstance(dets, list)
    assert vis.shape == img.shape
    assert state["backend"].startswith("mobilenetv3_5class_")
    assert state["ok"] is True
    assert state["reason"] == "ok"
    assert "tried" not in state
    assert state["patches"] == 1
    assert state["conf_used"] == 0.60
    for d in dets:
        assert set(d) >= {
            "x",
            "y",
            "w",
            "h",
            "xc",
            "yc",
            "class_id",
            "class_name",
            "confidence",
            "window_count",
        }


def test_yolo_detect_sliced_aliases_once(tiny_checkpoint):
    _init_tiny(tiny_checkpoint)
    img = np.zeros((300, 500, 3), dtype=np.uint8)
    dets1, vis1, state1 = yolo_detect_once(img)
    dets2, vis2, state2 = yolo_detect_sliced(img)
    assert dets2 == dets1
    assert vis2.shape == vis1.shape == img.shape
    assert state2 == state1


def test_yolo_detect_auto_retry_contract(tiny_checkpoint):
    _init_tiny(tiny_checkpoint)
    img = np.zeros((300, 500, 3), dtype=np.uint8)
    dets, vis, state = yolo_detect_auto_retry(img, start_conf=0.5)
    assert "tried" in state
    tried = state["tried"]
    assert len(tried) == 1
    assert tried[0]["try"] == 1
    assert "conf" in tried[0]
    assert tried[0]["conf"] == 0.5
    assert tried[0]["count"] == len(dets)
    assert tried[0]["state"] == "ok"
