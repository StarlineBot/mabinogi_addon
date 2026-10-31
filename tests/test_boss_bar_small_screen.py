"""0.31.2 QA: 1440 미만 화면(1920×1080 창 모드, 게임 약 1902×977)에서도 보스바는 521×37 — 화면 비율로 줄이지 않는다.

0.30.1~0.31.1은 1440 미만에서 UI가 작아진다고 보고(ui_scale = H/1440) 바 높이를 28px로 정규화해 HP를 못 읽었고
(보스 패턴 알림 안 뜸), 자동 찾기 후보 (698,822,521,28)도 검증에서 떨어졌다. 손으로 잡은 박스도 판독 직전 같은 정규화.
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect import boss_hp_reader, boss_name_matcher
from mabinogi_addon.detect.boss_bar import normalize_box_height


def test_1080_window_boss_bar_found_read_and_named():
    frame = image_io.imread("tests/data/image01.png", cv2.IMREAD_COLOR)  # 고목의 페타크 99.95%
    box = run_detector("boss", frame, detector_assets("boss"), {})
    assert box is not None
    x, y, w, h = box
    assert abs(x - 698) <= 2 and abs(y - 817) <= 2 and abs(w - 521) <= 2 and h == 37
    bar = frame[y:y + h, x:x + w]
    assert boss_hp_reader.read_percent(bar) == 99
    assert boss_name_matcher.identify(bar[:, :int(w * 0.60)]) == "gomok_petak"


def test_hand_drawn_box_on_1080_screen_is_read():
    frame = image_io.imread("tests/data/image01.png", cv2.IMREAD_COLOR)
    x, y, w, h = normalize_box_height((698, 810, 521, 50), frame.shape[0])  # 손으로 크게 잡은 박스
    assert h == 37 and boss_hp_reader.read_percent(frame[y:y + h, x:x + w]) == 99


SHOTS_1080 = {  # 앱 v0.31.1 화면 함께 찍힌 장: 자동 찾기 상자, HP, 이름(목록 밖은 None)
    "image02.png": ((703, 818, 521, 37), 99, None),  # 브론타나스 99.99% — 지원 목록 밖
    "image03.png": ((703, 818, 518, 37), 100, "lenen_miir"),
    "image04.png": ((703, 818, 518, 37), 100, "lenen_miir_hoehan"),
}


@pytest.mark.parametrize("name", sorted(SHOTS_1080))
def test_1080_autofind_and_hand_box(name):
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    box, percent, boss = SHOTS_1080[name]
    assert run_detector("boss", frame, detector_assets("boss"), {}) == box
    # 앱에서 손으로 잡은 박스(700,818,528,46)도 판독 직전 정규화 경로로 같은 값(예전 28px → HP None)
    x, y, w, h = normalize_box_height((700, 818, 528, 46), frame.shape[0])
    bar = frame[y:y + h, x:x + w]
    assert h == 37 and boss_hp_reader.read_percent(bar) == percent
    assert boss_name_matcher.identify(bar[:, :int(w * 0.60)]) == boss


def test_hoehan_halo_autofind_with_many_white_dots():
    """image04 회한 '14:43': 날개 효과로 위쪽 흰 점 74개(> 예전 상한 64) → 후보 탐색 포기였다. 이제 콜론 쌍 수로 판단."""
    from mabinogi_addon.detect import halo_timer
    frame = image_io.imread("tests/data/image04.png", cv2.IMREAD_COLOR)
    box = run_detector("halo_timer", frame, detector_assets("halo_timer"), {})
    assert box is not None
    x, y, w, h = box
    assert halo_timer.read_seconds(frame[y:y + h, x:x + w]) == 14 * 60 + 43


class _Watcher:
    def is_game_active(self):
        return False

    def is_self_active(self):
        return True


def test_preview_fits_label_width():
    """판독 미리보기: 높이 38로 키운 띠가 라벨보다 넓으면 양쪽이 잘렸다 → 라벨 폭 안에 비율 유지 축소."""
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui.boss_tab import BossTab
    QApplication.instance() or QApplication([])
    frame = image_io.imread("tests/data/image02.png", cv2.IMREAD_COLOR)
    tab = BossTab(_Watcher())
    tab.preview.setFixedWidth(300)
    tab._show_preview(frame[810:856, 700:1228])  # 528×46 손 지정 박스(예전 높이 38 → 폭 436)
    pixmap = tab.preview.pixmap()
    assert pixmap.width() <= tab.preview.contentsRect().width() and pixmap.height() <= 38
    assert abs(pixmap.height() - pixmap.width() * 46 / 528) <= 1  # 가로·세로 비율 유지(반올림 1px)
    tab.shutdown()
