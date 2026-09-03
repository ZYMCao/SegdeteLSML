"""
Smoke tests for the SegDete Label Studio ML backend.

These exercise the model class in isolation (no live Label Studio server).
Checks that depend on the (heavy) SegDete 5-class runtime are skipped
gracefully when the checkpoint is not available in the current environment.

Run from the repo root:
    cd lsml && uv run pytest src/lsml/test_api.py -v
"""

import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import model


def _seed_bgr(size=(96, 128)):
    rng = np.random.default_rng(0)
    return (rng.random((size[0], size[1], 3)) * 255).astype(np.uint8)

def test_lsml_is_importable_as_package():
    import lsml
    import lsml._wsgi
    from lsml.model import SegDeteMLBackend as PkgModel

    assert PkgModel.__name__ == "SegDeteMLBackend"
    assert lsml._wsgi.SegDeteMLBackend is PkgModel
    assert not os.path.exists(os.path.join(HERE, "__init__.py"))


def test_load_bgr_roundtrip(tmp_path):
    import cv2

    src = _seed_bgr()
    p = tmp_path / "img.png"
    cv2.imwrite(str(p), src)
    arr = model._load_bgr(str(p))
    assert arr is not None and arr.ndim == 3 and arr.shape == src.shape


def _make_backend():
    try:
        return model.SegDeteMLBackend()
    except Exception as exc:  # pragma: no cover - runtime/model unavailable
        pytest.skip(f"SegDete 5-class runtime unavailable locally: {exc}")


# ----------------------------------------------------------------------
# Pure helpers (no heavy runtime required)
# ----------------------------------------------------------------------

def test_resolve_control_names_uses_parsed_config():
    parsed = {"label": {"type": "RectangleLabels", "to_name": ["image"]}}
    assert model.resolve_control_names(parsed) == ("label", "image")
    assert model.resolve_control_names({}) == ("label", "image")
    assert model.resolve_control_names({"kind": {"type": "Choices"}}) == ("label", "image")
    assert model.resolve_control_names(
        {"rect": {"type": "RectangleLabels", "to_name": []}}, default_from="f", default_to="t"
    ) == ("rect", "t")


def test_crop_region_box_and_point():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    crop, box = model.crop_region(img, {"x": 10, "y": 20, "width": 10, "height": 5})
    assert box == (20, 20, 20, 5)
    assert crop.shape == (5, 20, 3)
    crop2, box2 = model.crop_region(img, {"x": 50, "y": 50})
    assert box2 is not None
    assert crop2.shape == (box2[3], box2[2], 3)


def test_crop_region_degenerate_returns_none():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    assert model.crop_region(img, {"x": 500, "y": 500, "width": 10, "height": 10}) == (None, None)


def test_remap_crop_results_identity_and_offset():
    result = {
        "id": "r0",
        "type": "rectanglelabels",
        "value": {"rectanglelabels": ["正常"], "x": 50, "y": 50, "width": 20, "height": 10},
        "from_name": "label",
        "to_name": "image",
        "score": 0.9,
    }
    out = model.remap_crop_results([result], (10, 20, 40, 30), (100, 200, 3))
    assert len(out) == 1
    v = out[0]["value"]
    assert v["x"] == 15.0          # px 30 -> 15%
    assert v["y"] == 35.0          # px 35 -> 35%
    assert v["width"] == 4.0       # 8px -> 4%
    assert out[0]["from_name"] == "label" and out[0]["to_name"] == "image"
    assert out[0]["id"] != "r0"


# ----------------------------------------------------------------------
# Runtime-dependent behavior (skipped if checkpoint unavailable)
# ----------------------------------------------------------------------

def test_predict_image_returns_result_schema():
    backend = _make_backend()
    img = _seed_bgr()
    results, score, meta = backend.predict_image(img)
    assert isinstance(results, list)
    assert isinstance(score, float)
    assert "det_count" in meta and "class_pred" in meta
    for r in results:
        assert r["type"] == "rectanglelabels"
        assert r["to_name"] == backend.to_name
        assert r["from_name"] == backend.from_name
        v = r["value"]
        assert {"rectanglelabels", "x", "y", "width", "height"} <= set(v)
        assert 0.0 <= v["x"] <= 100.0 and 0.0 <= v["y"] <= 100.0


def _install_fake_get_local_path(monkeypatch, tmp_path, img):
    import cv2

    calls = []

    def fake(url, *, hostname=None, access_token=None, task_id=None):
        p = tmp_path / f"img_{task_id or 'na'}.png"
        cv2.imwrite(str(p), img)
        calls.append({"url": url, "hostname": hostname, "access_token": access_token, "task_id": task_id})
        return str(p)

    monkeypatch.setattr(model, "get_local_path", fake)
    return calls


def test_predict_downloads_s3_with_task_id(monkeypatch, tmp_path):
    backend = _make_backend()
    calls = _install_fake_get_local_path(monkeypatch, tmp_path, _seed_bgr())
    tasks = [
        {"id": "T1", "data": {"image": "s3://segdete/in/a.jpg"}},
        {"id": "T2", "data": {"image": "s3://segdete/in/b.jpg"}},
    ]
    preds = backend.predict(tasks, None)
    assert len(preds) == len(tasks)
    assert [c["task_id"] for c in calls] == ["T1", "T2"]
    assert all(c["url"].startswith("s3://") for c in calls)
    assert all(p["model_version"] == backend.model_version for p in preds)


def test_batch_predict_returns_prediction_schema(monkeypatch, tmp_path):
    backend = _make_backend()
    _install_fake_get_local_path(monkeypatch, tmp_path, _seed_bgr())
    tasks = [{"id": 1, "data": {"image": "s3://segdete/in/a.jpg"}}]
    preds = backend.predict(tasks, None, login="user", password="pw")
    assert set(preds[0]) == {"result", "score", "model_version"}


def test_missing_image_field_returns_empty():
    backend = _make_backend()
    tasks = [{"id": 1, "data": {}}, {"id": 2, "data": {}}]
    preds = backend.predict(tasks, None)
    assert preds[0]["result"] == []
    assert preds[1]["result"] == []
    assert preds[0]["result"] is not preds[1]["result"]


def test_interactive_boxes_remap_to_full_image_and_attach_parent_id(monkeypatch, tmp_path):
    backend = _make_backend()
    _install_fake_get_local_path(monkeypatch, tmp_path, _seed_bgr())
    context = {
        "result": [
            {"id": "p1", "type": "rectanglelabels",
             "value": {"x": 0, "y": 0, "width": 100, "height": 100}}
        ]
    }
    preds = backend.predict([{"id": 1, "data": {"image": "s3://segdete/in/a.jpg"}}], context)
    for r in preds[0]["result"]:
        assert r["parent_id"] == "p1"
        assert r["type"] == "rectanglelabels"
        assert r["from_name"] == backend.from_name
        v = r["value"]
        assert 0.0 <= v["x"] <= 100.0 and 0.0 <= v["y"] <= 100.0


def test_interactive_point_click_and_degenerate_fallback(monkeypatch, tmp_path):
    backend = _make_backend()
    _install_fake_get_local_path(monkeypatch, tmp_path, _seed_bgr())
    task = {"id": 1, "data": {"image": "s3://segdete/in/a.jpg"}}
    point_preds = backend.predict(
        [task], {"result": [{"id": "p2", "type": "keypointlabels", "value": {"x": 50, "y": 50}}]}
    )
    assert point_preds[0]["result"] is not None
    for r in point_preds[0]["result"]:
        assert r["parent_id"] == "p2"
    degenerate_preds = backend.predict(
        [task],
        {"result": [{"id": "p3", "type": "rectanglelabels",
                     "value": {"x": 200, "y": 200, "width": 10, "height": 10}}]},
    )
    for r in degenerate_preds[0]["result"]:
        assert r["parent_id"] == "p3"