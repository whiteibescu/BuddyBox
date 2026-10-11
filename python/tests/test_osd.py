import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.follow.sensors import OsdSensorSource
from buddybox.vision.osd import (DEFAULT_D2, DEFAULT_RF, GlyphBook, OsdGrid, OsdReader, d2_text, decode_pos,
                                 element_cells, fit_grid, osd_pos, parse_d2, parse_rf, rf_text, text_mask)

W, H = 1920, 1080


def render(rf, d2, grid=None, noise=False):
    """합성 OSD 프레임: 회색 배경(+노이즈) 위에 흰 글자 + 검은 외곽선, 53×20 셀 격자."""
    grid = (grid or OsdGrid()).resolved(W, H)
    rng = np.random.default_rng(0)
    frame = (rng.integers(40, 140, (H, W, 3), dtype=np.uint8) if noise
             else np.full((H, W, 3), 90, np.uint8))
    for elem, text in ((DEFAULT_RF, rf), (DEFAULT_D2, d2)):
        for i, ch in enumerate(text):
            if ch == " ":
                continue
            x, y, w, h = grid.cell_box(elem.col + i, elem.row, W, H)
            org = (x + 4, y + h - 12)
            # 검은 외곽선: 8방향 오프셋으로 그린다 (OpenCV 5 는 굵은 글자를 덧그리면 완전히 덮는다)
            for dx in (-2, 0, 2):
                for dy in (-2, 0, 2):
                    if dx or dy:
                        cv2.putText(frame, ch, (org[0] + dx, org[1] + dy), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                                    (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, ch, org, cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 3, cv2.LINE_AA)
    return frame


def learn_book(book, samples):
    for rf, d2 in samples:
        mask = text_mask(render(rf, d2))
        for elem, text in ((DEFAULT_RF, rf), (DEFAULT_D2, d2)):
            for cell, ch in zip(element_cells(mask, book.grid, elem), text):
                book.learn(cell, ch)
    return book


def test_osd_pos_matches_betaflight_encoding():
    assert osd_pos(3, 16) == 2563                     # 기존 백업의 osd_vbat_pos
    assert decode_pos(2563) == (3, 16, (1,), 0)
    assert decode_pos(osd_pos(40, 18, profiles=(1, 2))) == (40, 18, (1, 2), 0)
    assert osd_pos(40, 0) & (1 << 10)                 # HD X 비트
    assert osd_pos(1, 18) == 2625 and osd_pos(10, 18) == 2634


def test_text_formats_and_parsers():
    assert rf_text(88) == "RF: 88" and rf_text(None) == "RF:---" and rf_text(0) == "RF:---"
    assert parse_rf("RF: 88") == 0.88 and parse_rf("RF:---") is None and parse_rf("RF:120") == 1.2
    assert d2_text([0, 0, 0, 0, 12, -345, 6, -7]) == "D2    12  -345     6    -7"
    assert parse_d2("D2    12  -345     6    -7") == [12, -345, 6, -7]
    with pytest.raises(ValueError):
        parse_rf("R?: 88")
    with pytest.raises(ValueError):
        parse_d2("D2 1 2 3")


def test_learn_then_read_synthetic_osd():
    book = learn_book(GlyphBook(), [
        (rf_text(123), d2_text([0, 0, 0, 0, 456, -789, 10, -2])),
        (rf_text(90), d2_text([0, 0, 0, 0, -3, 4, 567, 8])),
        (rf_text(None), d2_text([0, 0, 0, 0, 0, 0, 0, 0])),
    ])
    assert set("0123456789-:RFD") <= set(book.templates)
    reader = OsdReader(book)
    r = reader.read(render(rf_text(207), d2_text([0, 0, 0, 0, -45, 300, 98, -1]), noise=True))
    assert r.ok, (r.rf_text, r.d2_text, r.error)
    assert r.alt_m == 2.07 and r.debug == [0, 0, 0, 0, -45, 300, 98, -1]
    r = reader.read(render("RF:---", d2_text([0, 0, 0, 0, 0, 0, 0, 0])))
    assert r.ok and r.alt_m is None


def test_reader_reports_failure_on_blank_frame():
    book = learn_book(GlyphBook(), [(rf_text(50), d2_text([0, 0, 0, 0, 1, 2, 3, 4]))])
    r = OsdReader(book).read(np.full((H, W, 3), 90, np.uint8))
    assert not r.ok and "RF" in r.error


def test_glyphbook_save_load_roundtrip(tmp_path):
    book = learn_book(GlyphBook(grid=OsdGrid(x0=3.0, y0=2.0)), [(rf_text(77), d2_text([0] * 8))])
    path = book.save(tmp_path / "g.json")
    loaded = GlyphBook.load(path)
    assert loaded.grid.x0 == 3.0 and set(loaded.templates) == set(book.templates)
    assert np.allclose(loaded.templates["7"], book.templates["7"], atol=1e-3)


def test_fit_grid_recovers_horizontal_shift():
    shifted = OsdGrid(x0=12.0)
    mask = text_mask(render(rf_text(55), d2_text([0] * 8), grid=shifted))
    g, _ = fit_grid(mask, OsdGrid())
    assert abs(g.x0 - 12.0) < 0.3 * (W / 53)


def test_osd_sensor_source_feeds_samples():
    book = learn_book(GlyphBook(), [
        (rf_text(123), d2_text([0, 0, 0, 0, 456, -789, 10, -2])),
        (rf_text(90), d2_text([0, 0, 0, 0, -3, 4, 567, 8])),
        (rf_text(None), d2_text([0] * 8)),
    ])
    src = OsdSensorSource(OsdReader(book), every=2)
    f1 = render(rf_text(100), d2_text([0, 0, 0, 0, 0, 0, 200, -100]))
    assert src.feed(f1, now=1.0) is not None
    assert src.feed(f1, now=1.1) is None            # every=2 → 건너뜀
    s = src.latest()
    assert s.alt_m == 1.0 and abs(s.flow_x - 0.2) < 1e-9 and abs(s.vy + 0.1) < 1e-9 and s.t == 1.0
    assert src.feed(np.full((H, W, 3), 90, np.uint8), now=1.2) is None
    assert src.errors == 1 and src.latest().error
