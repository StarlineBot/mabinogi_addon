"""버프·디버프 아이콘 직접 지정 개선(docs/icon-capture-spec.md 2.1~2.3, 제작자 먼저).

① 테두리 자동 맞춤: 실화면 클릭 좌표 → 정확한 16×16, 아이콘 아닌 곳 → 없음. 저장 파일 16×16.
② 미리보기: 원본 픽셀 정수배(100·125·150·200%).
③ 온전히 보일 때만 저장: 깜빡임·꺼짐(회색)·가려짐 → 저장 안 함 + 이유, 정상 → 가장 밝은 안정 프레임.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect import icon_snap as snap

DATA = Path(__file__).parent / "data"


def _read(name):
    return image_io.imread(DATA / name, cv2.IMREAD_COLOR)


# ---- ① 테두리 자동 맞춤 ------------------------------------------------------------------------
@pytest.mark.parametrize("name,icon,clicks", [
    ("image01.png", (116, 787), [(124, 795), (117, 788), (130, 801)]),  # 1080 상태 목록 마법 공격력
    ("image01.png", (116, 739), [(124, 747), (129, 740)]),              # 1080 상태 목록 음악 강화
    ("스크린샷 2026-10-09 201512.png", (1277, 1214), [(1285, 1222), (1279, 1227)]),  # 2560 펠롬 디버프 줄(모모)
    ("스크린샷 2026-10-09 201512.png", (1205, 1214), [(1213, 1222), (1218, 1215)]),  # 2560 펠롬 디버프 줄(방해 카드)
])
def test_click_snaps_to_exact_16px_icon(name, icon, clicks):
    frame = _read(name)
    for x, y in clicks:
        assert snap.find_icon(frame, x, y) == (*icon, 16, 16), (x, y)


def test_4k_favorite_rows_are_16px_and_off_icons_snap_too():
    """4K(010804)도 상태 목록 아이콘은 16px. 꺼진(어두운) 즐겨찾기도 테두리에 맞춰져 '꺼진 버프' 이유를 받을 수 있다."""
    frame = _read("mabinogi_2026_11_04_010804.png")
    for x, y in ((3550, 916), (3550, 940), (3550, 820)):  # 켜짐: 행진곡·한 아드레날린·프리미엄 전투
        assert snap.find_icon(frame, x + 8, y + 8) == (x, y, 16, 16)
        assert snap.ring_brightness(frame[y:y + 16, x:x + 16]) > snap.DIM_RATIO
    for x, y in ((3550, 796), (3550, 772)):  # 꺼짐: 다크 에르그·에고 인카네이트
        assert snap.find_icon(frame, x + 8, y + 8) == (x, y, 16, 16)
        cell = frame[y:y + 16, x:x + 16].copy()
        assert snap.pick_whole([cell] * 6, check_ring=True) == (None, snap.GRAY)


@pytest.mark.parametrize("name,click", [
    ("image01.png", (960, 300)),                       # 하늘·필드
    ("image01.png", (300, 795)),                       # 상태 목록 글자 위
    ("스크린샷 2026-10-09 201512.png", (1400, 1180)),  # 보스바 근처 빈 곳
])
def test_non_icon_click_finds_nothing(name, click):
    assert snap.find_icon(_read(name), *click) is None


def test_off_favorite_icons_are_dim_and_on_icons_are_not():
    """창 모드 wireweb_1 즐겨찾기 줄: 꺼진 아이콘은 테두리 밝기 0.46~0.51, 켜진 아이콘 0.92 이상(실측)."""
    from mabinogi_addon.catalog import build_templates, load_catalog
    from mabinogi_addon.detect import detect_buffs, favorites
    frame = _read("2026-10-30_windowed_wireweb_2.png")
    x, y, w, h = (2177, 317, 304, 1093)
    region = frame[y:y + h, x:x + w]
    templates = build_templates(load_catalog())
    reader = favorites.FavoritesReader(templates, (0, 50))
    ys = [d.y for d in detect_buffs(region, templates, (0, 50))]
    for _ in range(reader.CONFIRM_FRAMES * reader.SCAN_EVERY):
        reader.update(region, ys)
    seen = {True: [], False: []}
    for bid, row in reader.rows.items():
        cell = region[row.y:row.y + row.size, row.x:row.x + row.size]
        seen[bool(reader.on.get(bid))].append(snap.ring_brightness(cell))
    assert seen[True] and seen[False]
    assert max(seen[False]) < snap.DIM_RATIO < min(seen[True])


# ---- ③ 온전히 보일 때만 저장 ----------------------------------------------------------------------
def _icon():
    frame = _read("image01.png")
    return frame[787:803, 116:132].copy()


def _dim(img, k=0.5):
    return np.clip(img.astype(np.float32) * k, 0, 255).astype(np.uint8)


def test_steady_icon_saves_brightest_stable_frame():
    icon = _icon()
    brighter = np.clip(icon.astype(np.int16) + 6, 0, 255).astype(np.uint8)
    frames = [icon, icon, brighter, brighter, icon, icon]
    got, reason = snap.pick_whole(frames, check_ring=True)
    assert reason is None and got is not None and np.array_equal(got, brighter)


def test_blinking_buff_is_not_saved():
    icon = _icon()
    frames = [icon, _dim(icon), icon, _dim(icon), icon, _dim(icon)]  # 끝나 갈 때 깜빡임(프레임마다 밝기 다름)
    assert snap.pick_whole(frames, check_ring=True) == (None, snap.BLINK)


def test_off_gray_favorite_is_not_saved():
    off = _dim(_icon(), 0.48)  # 꺼진 즐겨찾기 실측과 같은 밝기(0.46~0.51)
    assert snap.pick_whole([off] * 6, check_ring=True) == (None, snap.GRAY)


def test_real_off_favorite_crop_is_gray():
    frame = _read("2026-10-30_windowed_wireweb_2.png")
    from mabinogi_addon.catalog import build_templates, load_catalog
    from mabinogi_addon.detect import detect_buffs, favorites
    x, y, w, h = (2177, 317, 304, 1093)
    region = frame[y:y + h, x:x + w]
    templates = build_templates(load_catalog())
    reader = favorites.FavoritesReader(templates, (0, 50))
    ys = [d.y for d in detect_buffs(region, templates, (0, 50))]
    for _ in range(reader.CONFIRM_FRAMES * reader.SCAN_EVERY):
        reader.update(region, ys)
    row = reader.rows["magic_attack"]
    assert not reader.on["magic_attack"]
    cell = region[row.y:row.y + row.size, row.x:row.x + row.size].copy()
    assert snap.pick_whole([cell] * 6, check_ring=True) == (None, snap.GRAY)


def test_covered_icon_is_not_saved():
    rng = np.random.default_rng(0)
    covered = [rng.integers(0, 255, (16, 16, 3), dtype=np.uint8) for _ in range(6)]  # 툴팁·다른 창이 덮음
    assert snap.pick_whole(covered, check_ring=True) == (None, snap.COVERED)


def test_drag_pick_skips_ring_check_but_still_rejects_blink():
    frame = _read("image01.png")
    crop = frame[780:812, 108:140].copy()  # 손으로 드래그한 크기(아이콘 + 주변)
    got, reason = snap.pick_whole([crop] * 6, check_ring=False)
    assert reason is None and got.shape == crop.shape  # 드래그 저장 크기는 그대로
    dim = _dim(crop)
    assert snap.pick_whole([crop, dim] * 3, check_ring=False) == (None, snap.BLINK)


def test_verify_pick_regrabs_six_times_without_ui():
    icon = _icon()
    calls, sleeps = [], []

    def grab(x, y, w, h):
        calls.append((x, y, w, h))
        return icon
    got, reason = snap.verify_pick(grab, (5, 6, 16, 16), snapped=True, sleep=sleeps.append)
    assert reason is None and len(calls) == 6 and sleeps == [0.1] * 5


def test_reason_texts():
    assert snap.REASONS[snap.BLINK].startswith("버프가 깜빡이는 중이에요")
    assert snap.REASONS[snap.GRAY].startswith("꺼진(회색) 버프예요")
    assert snap.REASONS[snap.COVERED] == "아이콘이 가려졌어요"


# ---- 선택창: 클릭 = 16×16 그대로 저장, 아이콘 아닌 곳 클릭 = 아무 일 없음 ------------------------------------
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _selector(tmp_path, frame):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPixmap

    from mabinogi_addon.ui.region_selector import RegionSelector
    sel = RegionSelector(save_path=tmp_path / "icon.png", icon_snap=True)
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
    sel._shot, sel._dpr = QPixmap.fromImage(img), 1.0
    sel._icon_frame = frame
    sel._screen_geo = sel._screen_geo.__class__(0, 0, frame.shape[1], frame.shape[0])
    return sel, QPoint


def test_selector_click_saves_exact_16px_and_reports_physical_rect(app, tmp_path):
    frame = _read("image01.png")
    sel, QPoint = _selector(tmp_path, frame)
    got = {}
    sel.picked.connect(got.update)
    saved = []
    sel.captured.connect(saved.append)
    sel._cursor = QPoint(124, 795)
    sel._update_hover()
    assert sel._hover.rect == (116, 787, 16, 16)
    sel._origin = QPoint(124, 795)
    sel.mouseReleaseEvent(None)
    assert saved == [True] and got == {"rect": (116, 787, 16, 16), "snapped": True}
    out = image_io.imread(tmp_path / "icon.png", cv2.IMREAD_COLOR)
    assert out.shape == (16, 16, 3) and np.array_equal(out, frame[787:803, 116:132])


def test_selector_click_on_non_icon_does_nothing(app, tmp_path):
    sel, QPoint = _selector(tmp_path, _read("image01.png"))
    saved = []
    sel.captured.connect(saved.append)
    sel._cursor = QPoint(960, 300)
    sel._update_hover()
    sel._origin = QPoint(960, 300)
    sel.mouseReleaseEvent(None)
    assert sel._hover is None and saved == [] and not sel._finished and not (tmp_path / "icon.png").exists()
    sel.close()


def test_selector_drag_saves_dragged_size_as_before(app, tmp_path):
    from PySide6.QtCore import QRect
    frame = _read("image01.png")
    sel, QPoint = _selector(tmp_path, frame)
    got = {}
    sel.picked.connect(got.update)
    sel._origin, sel._dragging, sel._rect = QPoint(110, 780), True, QRect(110, 780, 22, 25)
    sel.mouseReleaseEvent(None)
    assert got == {"rect": (110, 780, 22, 25), "snapped": False}
    assert image_io.imread(tmp_path / "icon.png", cv2.IMREAD_COLOR).shape == (25, 22, 3)


def test_non_creator_selector_has_no_icon_snap(app, tmp_path):
    from mabinogi_addon.ui.region_selector import RegionSelector
    sel = RegionSelector(save_path=tmp_path / "x.png")
    assert not sel._icon_snap


# ---- ② 미리보기 원본 픽셀 정수배 ----------------------------------------------------------------------
@pytest.mark.parametrize("dpr,k", [(1.0, 2), (1.25, 3), (1.5, 3), (2.0, 5)])
def test_preview_is_integer_multiple_of_source_pixels(app, dpr, k):
    from PySide6.QtGui import QImage

    from mabinogi_addon.ui.buff_tab import crisp_pixmap
    icon = _icon()
    rgb = np.ascontiguousarray(icon[:, :, ::-1])
    img = QImage(rgb.data, 16, 16, rgb.strides[0], QImage.Format.Format_RGB888).copy()
    pm = crisp_pixmap(img, 40, dpr)
    phys = round(40 * dpr)
    assert pm.width() == phys and pm.devicePixelRatio() == dpr  # Qt가 다시 늘리지 않게
    out = pm.toImage().convertToFormat(QImage.Format.Format_RGB888)
    arr = np.frombuffer(out.constBits(), np.uint8, count=out.bytesPerLine() * phys).reshape(phys, out.bytesPerLine())
    arr = arr[:, : phys * 3].reshape(phys, phys, 3)[:, :, ::-1]
    off = (phys - 16 * k) // 2
    drawn = arr[off:off + 16 * k, off:off + 16 * k]
    assert np.array_equal(drawn, np.repeat(np.repeat(icon, k, axis=0), k, axis=1))  # 원본 한 픽셀 = k×k 블록 그대로
