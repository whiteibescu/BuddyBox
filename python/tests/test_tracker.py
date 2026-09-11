import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.vision.tracker import TargetTracker, iou


def box(cx, cy, w, h, conf=0.9):
    return (conf, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def test_iou_identity_and_disjoint():
    a = (0.1, 0.1, 0.5, 0.5)
    assert abs(iou(a, a) - 1.0) < 1e-9
    assert iou(a, (0.6, 0.6, 0.9, 0.9)) == 0.0


def test_picks_tallest_person_when_no_target():
    tr = TargetTracker()
    t = tr.update([box(0.2, 0.5, 0.1, 0.2), box(0.7, 0.5, 0.2, 0.6)], now=0.0)
    assert abs(t.cx - 0.7) < 1e-9
    assert abs(t.h - 0.6) < 1e-9
    assert not t.lost


def test_follows_nearest_and_ignores_far_jump():
    tr = TargetTracker(smoothing=1.0, max_jump=0.2)
    tr.update([box(0.5, 0.5, 0.2, 0.5)], now=0.0)
    t = tr.update([box(0.55, 0.5, 0.2, 0.5), box(0.95, 0.5, 0.3, 0.9)], now=0.1)
    assert abs(t.cx - 0.55) < 1e-9


def test_smoothing_moves_partially():
    tr = TargetTracker(smoothing=0.5)
    tr.update([box(0.5, 0.5, 0.2, 0.5)], now=0.0)
    t = tr.update([box(0.6, 0.5, 0.2, 0.5)], now=0.1)
    assert abs(t.cx - 0.55) < 1e-9


def test_lost_then_dropped_after_timeouts():
    tr = TargetTracker(lost_after_s=0.5, drop_after_s=1.5)
    tr.update([box(0.5, 0.5, 0.2, 0.5)], now=0.0)
    t = tr.update([], now=0.3)
    assert t is not None and not t.lost
    t = tr.update([], now=0.8)
    assert t is not None and t.lost
    assert tr.peek(now=2.0) is None
    assert not tr.has_target


def test_reacquires_after_drop():
    tr = TargetTracker(lost_after_s=0.2, drop_after_s=0.5)
    tr.update([box(0.2, 0.5, 0.1, 0.3)], now=0.0)
    tr.update([], now=1.0)
    t = tr.update([box(0.8, 0.5, 0.1, 0.4)], now=1.1)
    assert t is not None and abs(t.cx - 0.8) < 1e-9


def test_click_selects_box_under_point():
    tr = TargetTracker()
    tr.update([box(0.2, 0.5, 0.1, 0.3), box(0.8, 0.5, 0.2, 0.6)], now=0.0)
    tr.select_at(0.2, 0.5)
    t = tr.update([box(0.2, 0.5, 0.1, 0.3), box(0.8, 0.5, 0.2, 0.6)], now=0.1)
    assert abs(t.cx - 0.2) < 1e-9


def test_min_height_filters_small_boxes():
    tr = TargetTracker(min_height=0.1)
    assert tr.update([box(0.5, 0.5, 0.05, 0.05)], now=0.0) is None


def test_clear_forgets_target():
    tr = TargetTracker()
    tr.update([box(0.5, 0.5, 0.2, 0.5)], now=0.0)
    tr.clear()
    assert tr.peek(0.1) is None
