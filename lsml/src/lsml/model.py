"""
SegDete Label Studio ML backend.

Purpose: validate the NON-stitch computer-vision functions (classification +
5-class sliding-window detection) of SegDete on an independent image library,
using the LATEST SegDete code and model. It STRICTLY reuses SegDete business
logic (segdete.vision.*) — no CV logic is re-implemented here.

Each Label Studio task is a SINGLE image (a stitched panorama that was uploaded
to S3 `in/` by lsml/scripts/stitch_to_s3.py and synced into Label Studio). `predict()`
runs classification + detection and returns correctable RectangleLabels
pre-annotations over that image.

Three Label Studio capabilities are supported:

1. Batch pre-annotation ("Retrieve Predictions") — LS POSTs every task to
   `/predict` with `params.context = None`; we return one prediction per task.
2. Interactive pre-annotation (smart tools) — the frontend POSTs a drawn
   region through LS to `/predict` with `params.context = {"result": [region]}`.
   We crop the drawn box/point, run the same detection on the crop, remap the
   detections back to full-image percent coordinates and tag every suggestion
   with `parent_id` = the drawn region id.
3. Training — LS webhooks call `fit()`, which is an empty placeholder (the
   SegDete 5-class detector has fixed weights; no re-training is performed).
"""

import logging
import uuid

import cv2
import numpy as np
from label_studio_ml.model import LabelStudioMLBase
from label_studio_tools.core.utils.io import get_local_path

from segdete.config.vision.yolo import YoloConfig
from segdete.vision.classifier import MLClassifier
from segdete.vision.draw import _enrich_dets
from segdete.vision.yolo import init_yolo_config, yolo_detect_once


def _load_bgr(path):
    """Robust BGR load (handles Unicode paths via np.fromfile)."""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def resolve_control_names(parsed_label_config, default_from="label", default_to="image"):
    """Locate the RectangleLabels control in a parsed label config.

    ``parsed_label_config`` is the dict produced by label_studio_tools
    parse_config() (== the base class ``self.parsed_label_config``): keyed by
    control name, each value has "type" and "to_name" (a LIST of object names).
    """
    for control_name, cfg in (parsed_label_config or {}).items():
        if str(cfg.get("type", "")).lower() == "rectanglelabels":
            to_names = cfg.get("to_name") or []
            if isinstance(to_names, list) and to_names:
                return control_name, to_names[0]
            return control_name, default_to
    return default_from, default_to


def crop_region(img_bgr, value, det_window=768):
    """Convert a smart-tool context region ``value`` (percent 0-100) into a
    clamped pixel crop.

    Box regions (width and height > 0) use their box; point regions (width or
    height absent/zero) use a ``det_window``-sized square centered on the point.

    Returns ``(crop_bgr, (x0, y0, cw, ch))`` in full-image pixel coordinates,
    or ``(None, None)`` when the clamped crop is degenerate (zero area, e.g. a
    box fully outside the image).
    """
    H, W = img_bgr.shape[:2]
    x = float(value.get("x", 0.0)) / 100.0 * W
    y = float(value.get("y", 0.0)) / 100.0 * H
    w = float(value.get("width", 0.0)) / 100.0 * W
    h = float(value.get("height", 0.0)) / 100.0 * H
    if w > 0 and h > 0:
        x0, y0, x1, y1 = int(x), int(y), int(x + w), int(y + h)
    else:
        x0, y0 = int(x - det_window // 2), int(y - det_window // 2)
        x1, y1 = x0 + det_window, y0 + det_window
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return None, None
    return img_bgr[y0:y1, x0:x1], (x0, y0, x1 - x0, y1 - y0)


def remap_crop_results(results, crop_box, full_shape):
    """Map detection regions computed on a crop back to full-image percent
    coordinates, generating fresh ids."""
    cw, ch = crop_box[2], crop_box[3]
    cx0, cy0 = crop_box[0], crop_box[1]
    H, W = full_shape[:2]
    out = []
    for r in results:
        v = r["value"]
        out.append(
            {
                "id": str(uuid.uuid4()),
                "type": r["type"],
                "value": {
                    "rectanglelabels": list(v["rectanglelabels"]),
                    "x": round((cx0 + v["x"] / 100.0 * cw) / W * 100, 6),
                    "y": round((cy0 + v["y"] / 100.0 * ch) / H * 100, 6),
                    "width": round(v["width"] / 100.0 * cw / W * 100, 6),
                    "height": round(v["height"] / 100.0 * ch / H * 100, 6),
                },
                "from_name": r["from_name"],
                "to_name": r["to_name"],
                "score": r["score"],
            }
        )
    return out


class SegDeteMLBackend(LabelStudioMLBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Same YOLO / 5-class runtime config as production.
        yolo_cfg = YoloConfig().to_dict()
        init_yolo_config(yolo_cfg)
        self.det_window = int(yolo_cfg["classifier_window"])
        # Eagerly load the 5-class runtime so a missing/corrupt checkpoint
        # fails fast here instead of mid-prediction.
        self.classifier = MLClassifier()
        # Resolve labeling-control names from the project labeling config
        # (self.parsed_label_config is set by the SDK base class).
        self.from_name, self.to_name = resolve_control_names(self.parsed_label_config)
        self.model_version = "segdete-5class"

    def predict_image(self, img_bgr):
        """Core: classification + detection on ONE image.

        Returns (results, score, meta) where results is a list of
        Label Studio RectangleLabels pre-annotation dicts.
        """
        cls = self.classifier.predict(img_bgr)          # {"pred", "confidence"}
        dets, _vis, state = yolo_detect_once(img_bgr)   # latest 5-class model
        H, W = img_bgr.shape[:2]
        enriched = _enrich_dets(dets, H, W)

        results = []
        for name, d in zip(range(len(enriched)), enriched):
            nx, ny, nw, nh = d["bbox_norm"]
            results.append({
                "id": str(uuid.uuid4()),
                "type": "rectanglelabels",
                "value": {
                    "rectanglelabels": [d["class_name"]],
                    "x": round(nx * 100, 6),
                    "y": round(ny * 100, 6),
                    "width": round(nw * 100, 6),
                    "height": round(nh * 100, 6),
                },
                "from_name": self.from_name,
                "to_name": self.to_name,
                "score": round(d["confidence"], 6),
            })

        score = float(cls["confidence"]) if results else 0.0
        meta = {
            "class_pred": int(cls["pred"]),
            "class_confidence": float(cls["confidence"]),
            "det_count": len(enriched),
            "backend": state.get("backend", "unknown"),
            "model": state.get("model"),
        }
        return results, score, meta

    def _predict_interactive(self, img_bgr, context):
        """Run detection on the drawn region's crop and attach parent_id.

        context is the LS interactive context dict: {"result": [region]}; the
        frontend always sends at least one region. A degenerate crop (clamped
        to zero area) falls back to full-image inference; parent_id is attached
        to every suggestion either way.
        """
        region = context["result"][0]
        parent_id = region["id"]
        value = region.get("value") or {}
        crop, crop_box = crop_region(img_bgr, value, self.det_window)
        if crop is None:
            results, score, _ = self.predict_image(img_bgr)
        else:
            crop_results, score, _ = self.predict_image(crop)
            results = remap_crop_results(crop_results, crop_box, img_bgr.shape)
        for r in results:
            r["parent_id"] = parent_id
        return results, score

    def _empty_prediction(self):
        return {"result": [], "score": 0.0, "model_version": self.model_version}

    def predict(self, tasks, context=None, **kwargs):
        predictions = []
        for task in tasks:
            image_url = (task.get("data") or {}).get("image")
            if not image_url:
                predictions.append(self._empty_prediction())
                continue
            # Cloud-storage (s3://) URLs require task_id to be presigned via
            # {hostname}/tasks/{id}/presign/?fileuri=... by Label Studio.
            local_path = get_local_path(
                image_url,
                hostname=self.hostname,
                access_token=self.access_token,
                task_id=task.get("id"),
            )
            img = _load_bgr(local_path)
            if img is None:
                logging.warning(
                    "Cannot read image for task %s from %s", task.get("id"), image_url
                )
                predictions.append(self._empty_prediction())
                continue
            if context:
                results, score = self._predict_interactive(img, context)
            else:
                results, score, _ = self.predict_image(img)
            predictions.append({
                "result": results,
                "score": score,
                "model_version": self.model_version,
            })
        return predictions

    def fit(self, tasks, **kwargs):
        """Training placeholder. Webhook-driven events call fit((), ...); no
        real training is performed (the SegDete 5-class model has fixed
        weights)."""
        return {}