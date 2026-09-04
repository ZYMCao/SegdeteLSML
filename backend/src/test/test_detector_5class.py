from PIL import Image
import torch
from torch import nn
from torchvision import models

from segdete.vision.detector_5class import (
    CLASS_ZH,
    connected_components,
    infer,
    load_model,
    positions,
)


def _make_checkpoint(tmp_path):
    model = models.mobilenet_v3_large(weights=None)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, 5)
    ckpt = {"model": model.state_dict(), "classes": CLASS_ZH}
    path = tmp_path / "tiny_model.pth"
    torch.save(ckpt, path)
    return path


class TestPositions:
    def test_length_leq_window_returns_zero(self):
        assert positions(400, 768, 384) == [0]

    def test_exact_division(self):
        assert positions(768, 384, 384) == [0, 384]

    def test_non_divisible_tail(self):
        vals = positions(1000, 768, 384)
        assert vals[-1] == 1000 - 768 == 232


class TestConnectedComponents:
    def test_single_cell_is_one_group(self):
        groups = connected_components([(1, 1)], 3, 3)
        assert len(groups) == 1
        assert sorted(groups[0]) == [(1, 1)]

    def test_two_adjacent_cells_one_group(self):
        groups = connected_components([(1, 1), (1, 2)], 3, 3)
        assert len(groups) == 1
        assert sorted(groups[0]) == [(1, 1), (1, 2)]

    def test_two_separated_cells_two_groups(self):
        groups = connected_components([(0, 0), (2, 2)], 3, 3)
        assert len(groups) == 2
        assert sorted(sorted(g) for g in groups) == [[(0, 0)], [(2, 2)]]


class TestLoadModel:
    def test_loads_checkpoint_and_returns_eval_model(self, tmp_path):
        path = _make_checkpoint(tmp_path)
        model, ckpt = load_model(path, "cpu")
        assert isinstance(model.classifier[3], nn.Linear)
        assert model.classifier[3].out_features == 5
        assert not model.training
        assert "model" in ckpt
        assert "classes" in ckpt


class TestInfer:
    def test_smoke_infer_returns_cells_and_detections(self, tmp_path):
        path = _make_checkpoint(tmp_path)
        model, _ = load_model(path, "cpu")
        image = Image.new("RGB", (400, 300), color=(128, 128, 128))
        cells, detections = infer(
            image, model, "cpu", window=768, stride=384, batch_size=8, threshold=0.60
        )
        assert isinstance(cells, list)
        assert len(cells) == 1
        for cell in cells:
            assert set(cell) >= {
                "row",
                "col",
                "bbox",
                "class_id",
                "label",
                "confidence",
                "probabilities",
            }
            assert len(cell["probabilities"]) == 5
        assert isinstance(detections, list)
