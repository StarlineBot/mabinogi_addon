"""보스바 채움 경계가 숫자를 가로지를 때 앞자리만 읽던 것(17.48 → 1) — QA 8067a9c, 수집 unknown_hpxxx_show001_upper_197.zip.

판독기: 기본 판독은 그대로, 숫자 칸에 회색 빈 바 바탕이 있을 때만 회색을 뺀 마스크로 한 번 더 읽어 '늘리기만'(1→17).
tests/data 보스 자료 비교표(docs/status.md): 바뀐 결과는 이 두 프레임뿐, 소수 표시 수 같음.
오버레이 값 규칙: 직전 표시값의 앞자리만 남은 값(17→1, 55→5, 100→10)은 확정하지 않음.
"""
import zipfile

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect import boss_hp_reader as r
from mabinogi_addon.tracker.boss_bar_value import BossBarValue, truncated

ZIP = "tests/data/unknown_hpxxx_show001_upper_197.zip"
# 앱 입력과 같게: 등록 보스는 오른쪽 42%(boss_tab pct_reg·_read_row), 미등록은 전체 폭(검증기) — 둘 다 확인(QA b2b6534)
WIDTHS = pytest.mark.parametrize("part", ["right42", "full"])


def _cut(crop, part):
    return crop[:, int(crop.shape[1] * 0.58):] if part == "right42" else crop


def _frame(name):
    with zipfile.ZipFile(ZIP) as z:
        return cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)


@WIDTHS
@pytest.mark.parametrize("name", ["gomok_petak_hp001_129.png", "gomok_petak_hp001_show017_drop_130.png"])
def test_fill_edge_through_digit_reads_whole_number(name, part, monkeypatch):
    crop = _cut(_frame(name)[45:82], part)  # 등록 영역 줄 — 빨간 채움 끝이 '7' 한가운데
    monkeypatch.setattr(r, "USE_TEXT_MASK", False)
    assert r.read_percent(crop) == 1  # 예전: 앞자리만
    monkeypatch.setattr(r, "USE_TEXT_MASK", True)
    assert r.read_percent(crop) == 17 and r.read_percent_frac(crop)[0] == 17


def test_no_gray_in_number_area_means_no_extra_read(monkeypatch):
    """채움이 숫자 칸을 다 덮은 화면(대부분)은 보조 판독을 하지 않는다(판독 비용 그대로)."""
    import glob
    from mabinogi_addon import image_io
    from mabinogi_addon.detect.boss_bar import locate_boss_bar, make_validator
    f = image_io.imread("tests/data/스크린샷 2026-10-09 201512.png", cv2.IMREAD_COLOR)  # 펠롬 42%
    x, y, w, h = locate_boss_bar(f, make_validator())
    calls = []
    real = r._text_mask
    monkeypatch.setattr(r, "_text_mask", lambda img: (calls.append(1), real(img))[1])
    assert r.read_percent_frac(f[y:y + h, x:x + w])[0] == 42 and calls == []


def test_extend_never_reads_where_base_read_nothing():
    """기본 판독이 None이면 보조 판독도 없음(풍경에서 새 오독이 생기지 않게)."""
    assert r._extend(np.zeros((37, 521, 3), np.uint8), None, None, None, True) == (None, None)


@pytest.mark.parametrize("shown,value,expected", [(17, 1, True), (55, 5, True), (100, 10, True), (17, 16, False),
                                                  (10, 1, True), (12, 21, False), (5, 5, False), (100, 1, True)])
def test_truncated(shown, value, expected):
    assert truncated(value, shown) is expected


def test_overlay_value_does_not_confirm_truncated_reading():
    v = BossBarValue()
    assert v.update(17, "gomok_petak", 0.0).value == 17
    s = v.update(1, "gomok_petak", 0.3)
    assert s.value == 17 and s.stale and v.rule == "prefix"  # 17 → 1(앞자리만) 확정하지 않음
    s = v.update(1, "gomok_petak", 0.6)
    assert s.value == 17 and s.stale  # 두 번 이어져도(예전엔 확정됐다)
    s = v.update(16, "gomok_petak", 0.9)
    assert (s.value, s.stale) == (16, False)  # 실제 다음 값은 바로
    v2 = BossBarValue()
    v2.update(100, None, 0.0)
    assert v2.update(10, None, 0.3).value == 100  # 100 → 10
    v3 = BossBarValue()
    v3.update(55, None, 0.0)
    assert v3.update(5, None, 0.3).value == 55
    assert v3.update(5, None, 2.5).value is None  # 계속 그 꼴이면 1.8초 뒤 숨김(직전 값에 매달리지 않음)


# ---- 저HP(회색 바탕 위 흰 글자): 등록 영역이 바보다 5px 위로 어긋나면 '15.00'을 1로 읽던 것(사용자 11-07) ----------
@pytest.mark.parametrize("name,y,expected", [
    ("gomok_petak_hpxxx_161.png", 45, 13),                    # 13.00 % (아래 줄)
    ("gomok_petak_hp001_show015_drop_162.png", 45, 13),       # 13.00 % — QA 8067a9c의 162
    ("unknown_hpxxx_076.png", 45, 15),                        # 15.95 %
    ("gomok_petak_hp001_show055_drop_077.png", 45, 15),       # 15.95 %
    ("gomok_petak_hpxxx_135.png", 6, 15),                     # 15.00 % (위 줄)
    ("gomok_petak_hp010_show015_upper_157.png", 6, 15),
])
@WIDTHS
def test_low_hp_misaligned_band_reads_two_digits(name, y, expected, part, monkeypatch):
    crop = _cut(_frame(name)[y:y + 37], part)
    monkeypatch.setattr(r, "USE_TEXT_MASK", False)
    assert r.read_percent(crop) == 1  # 예전: 앞자리만
    monkeypatch.setattr(r, "USE_TEXT_MASK", True)
    assert r.read_percent(crop) == expected


@WIDTHS
def test_real_one_percent_stays_one(part):
    assert r.read_percent(_cut(_frame("gomok_petak_hp001_176.png")[45:82], part)) == 1  # 화면 1.62 %


# ---- 소수 첫째 자리 '1'(x.1x): 좁은 '1' 칸에 '.'이 같이 들어와 못 읽던 것(QA b2b6534) ------------------------------
@WIDTHS
@pytest.mark.parametrize("zip_name,name,expected", [
    ("eotgallin_poinche_hp004_115.zip", "eotgallin_poinche_hp035_013.png", (35, "10")),
    ("eotgallin_poinche_hp004_115.zip", "eotgallin_poinche_hp041_007.png", (41, "14")),
])
def test_fraction_with_narrow_one_after_dot(zip_name, name, expected, part, monkeypatch):
    with zipfile.ZipFile(f"tests/data/{zip_name}") as z:
        crop = cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)
    crop = _cut(crop, part)
    monkeypatch.setattr(r, "USE_TEXT_MASK", False)
    assert r.read_percent_frac(crop) == (expected[0], None)  # 예전: 소수 없음
    monkeypatch.setattr(r, "USE_TEXT_MASK", True)
    assert r.read_percent_frac(crop) == expected


# ---- 보스바 오버레이 눈금 글자(0%·25%·50%·75%·100%, 사용자 11-07) ---------------------------------------------------
def test_overlay_scale_strip_above_bar_keeps_saved_bar_position(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui import boss_bar_overlay as bo
    QApplication.instance() or QApplication([])
    ov = bo.BossBarOverlay(100)
    strip = ov._scale_h()
    assert strip > 0 and ov.height() == round(bo.BASE_H) + 4 + strip  # 바 위에 따로 한 줄(바를 가리지 않음)
    ov.set_scale(200)
    assert ov._scale_h() == round(bo.SCALE_H * bo.UNIT * 2) and ov.height() == round(bo.BASE_H * 2) + 4 + ov._scale_h()
    assert bo.SCALE_MARKS == (0, 25, 50, 75, 100)
    ov.close()


def test_saved_position_is_bar_top_so_bar_does_not_move(monkeypatch):
    """저장 위치는 바 위쪽 — 눈금 글자 줄을 더해도(배율을 바꿔도) 바는 같은 자리."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon import config, feature_access
    from mabinogi_addon.ui import boss_tab as bt
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)
    monkeypatch.setattr(bt.BossTab, "INLINE_JOBS", True)
    config.save_boss_bar_overlay({"enabled": True, "pos": {"x": 300, "y": 500}})
    from test_boss_bar_overlay import _Watcher
    tab = bt.BossTab(_Watcher())
    try:
        sec = tab.bar_section
        ov = sec._ensure_overlay()
        assert ov.y() + ov._scale_h() == 500  # 바 위쪽 = 저장한 자리(예전과 같음)
        sec._on_scale(200)
        assert ov.y() + ov._scale_h() == 500
        ov.moved.emit()
        assert config.load_boss_bar_overlay()["pos"]["y"] == 500
    finally:
        tab.shutdown()
