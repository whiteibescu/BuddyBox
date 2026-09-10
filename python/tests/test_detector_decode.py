import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
np = pytest.importorskip("numpy")
from buddybox.vision.detector import decode_rfdetr, persons

CLASSES = ["background", "person", "bicycle"]


def logits_for(cls_idx, strength=6.0, n=3):
    row = np.full(n, -strength, dtype=np.float32)
    row[cls_idx] = strength
    return row


def test_decode_scales_boxes_to_pixels_and_filters_threshold():
    boxes = np.array([[0.5, 0.5, 0.2, 0.4], [0.1, 0.1, 0.1, 0.1]], dtype=np.float32)
    logits = np.stack([logits_for(1), np.full(3, -3.0, dtype=np.float32)])
    dets = decode_rfdetr(boxes, logits, CLASSES, 0.5, 1920, 1080)
    assert len(dets) == 1
    d = dets[0]
    assert d.label == "person"
    assert (d.x1, d.y1, d.x2, d.y2) == (768, 324, 1152, 756)
    assert d.conf > 0.99


def test_decode_sorted_by_confidence_and_person_filter():
    boxes = np.array([[0.5, 0.5, 0.2, 0.4], [0.3, 0.3, 0.2, 0.2]], dtype=np.float32)
    logits = np.stack([logits_for(2, strength=2.0), logits_for(1, strength=5.0)])
    dets = decode_rfdetr(boxes, logits, CLASSES, 0.5, 100, 100)
    assert [d.label for d in dets] == ["person", "bicycle"]
    assert [d.label for d in persons(dets)] == ["person"]


def test_decode_empty_when_nothing_passes():
    boxes = np.zeros((4, 4), dtype=np.float32)
    logits = np.full((4, 3), -8.0, dtype=np.float32)
    assert decode_rfdetr(boxes, logits, CLASSES, 0.5, 100, 100) == []
