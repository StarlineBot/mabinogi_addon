"""0.33.0 브론타나스 보스 패턴(QA 요청, 사용자 결정 알림 체력 90·75·60·50·40·20%).

이름 템플릿은 '스크린샷 2026-10-09 185152' 이름 칸(y 1250:1290, x 1018:1300)을 boss_name_matcher._binary로 이진화해
높이 4px 이상·위아래 가장자리에 붙지 않은 글자 묶음 경계로 자른 것(17×80) — 같은 방법으로 185217을 자르면 기존 gomok_petak/name.png와 같다.
"""
import json

import cv2
import pytest

from mabinogi_addon import image_io, paths
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect import boss_hp_reader, boss_name_matcher

SHOTS = {  # 파일 → (자동 찾기 상자, HP)
    "스크린샷 2026-10-09 185152.png": ((1016, 1246, 521, 37), 100),
    "스크린샷 2026-10-15 213734.png": ((1016, 1246, 521, 37), 98),
    "2026-10-30_windowed_wireweb_2.png": ((1011, 1217, 521, 37), 99),
    "mabinogi_2026_10_30_214016.png": ((1658, 1968, 521, 37), 100),  # 4K
    "image02.png": ((703, 818, 521, 37), 99),  # 1080 창 모드
}


@pytest.mark.parametrize("name", sorted(SHOTS))
def test_brontanas_found_named_and_read(name):
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    box, percent = SHOTS[name]
    assert run_detector("boss", frame, detector_assets("boss"), {}) == box
    x, y, w, h = box
    bar = frame[y:y + h, x:x + w]
    assert boss_name_matcher.identify(bar[:, :int(w * 0.60)]) == "brontanas"
    assert boss_hp_reader.read_percent(bar) == percent


def test_brontanas_thresholds():
    data = json.loads((paths.resource_dir() / "boss/brontanas/patterns.json").read_text(encoding="utf-8"))
    assert data["name"] == "브론타나스" and data["thresholds"] == [90, 75, 60, 50, 40, 20]


def test_supported_order_puts_brontanas_between_petak_and_lenen():
    from mabinogi_addon.tracker.boss_catalog import load_bosses
    # 사용자 결정(2026-10-31): 포인셰 아래는 역순 — 포인셰 → 펠롬 → 회한 → 레넨 → 브론타나스 → 페타크
    assert list(load_bosses()) == ["eotgallin_poinche", "pellom", "lenen_miir_hoehan",
                                   "lenen_miir", "brontanas", "gomok_petak"]


def test_supported_list_shows_brontanas(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon import config
    from mabinogi_addon.ui.boss_tab import BossTab
    QApplication.instance() or QApplication([])

    class Watcher:
        def is_game_active(self):
            return False

        def is_self_active(self):
            return True
    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: None)
    tab = BossTab(Watcher())
    assert "브론타나스 — 90%, 75%, 60%, 50%, 40%, 20%" in tab._supported_label().text()
    tab.shutdown()
