"""0.39.1(제품 동작을 0.38.1로 되돌림) — 0.39.0이 쓴 설정을 0.38.1 코드가 읽어도 기존 영역·켜짐이 유지되는지.

0.39.0은 설정에 `autofind` 구역(찾은 위치 기억·선택·켜짐)과 공유 기능의 `use` 값을 더하고,
보스바를 쓰는 기능이 하나도 없으면 보스 영역을 '기억한 위치'(autofind.found.boss)로만 옮겼다.
0.38.1 코드는 이 값들을 읽지 않는다 — 모르는 키는 무시하고, 저장할 때도 지우지 않아야 다시 올렸을 때 이어진다.
"""
from copy import deepcopy

import pytest

from mabinogi_addon import config

B = {"x": 700, "y": 80, "w": 520, "h": 40}
H = {"x": 1150, "y": 120, "w": 70, "h": 24}
X = {"x": 933, "y": 948, "w": 28, "h": 23}
T = {"x": 980, "y": 948, "w": 40, "h": 23}
D = {"x": 700, "y": 20, "w": 300, "h": 100}
FOUND_AT = "2026-11-03T00:00:00+00:00"

V039 = {
    "autofind": {"enabled": True, "armed": True,
                 "selected": {"boss": True, "halo_timer": True, "dorcha": True, "tuarim": False},
                 "found": {"boss": {"box": B, "target": [1, 2, 0, 0, 1920, 1080], "found_at": FOUND_AT},
                           "dorcha": {"box": X, "target": None, "found_at": FOUND_AT}}},
    "bossPattern": {"use": True, "box": B, "showUpcoming": True},
    "haloTimer": {"use": True, "box": H},
    "debuffTracker": {"use": True, "captureRegion": D},
    "dorcha": {"enabled": True, "box": X},
    "tuarim": {"enabled": False, "box": T},
}


def _write(raw):
    config._write_local_config(deepcopy(raw))


def test_regions_and_switches_survive():
    _write(V039)
    assert config.load_boss_bar_region() == B
    assert config.load_boss_pattern()["showUpcoming"] is True
    assert config.load_capture_region("debuffTracker") == D
    d = config.load_dorcha()
    assert d["enabled"] is True and d["box"] == X
    t = config.load_tuarim()
    assert t["enabled"] is False and {k: t["box"][k] for k in "xywh"} == T
    assert config._read_local_config()["haloTimer"]["box"] == H


def test_saving_in_reverted_version_keeps_039_keys():
    """0.39.1에서 설정을 바꿔 저장해도 0.39.0의 autofind·use 값은 남는다(자동 찾기를 다시 출시할 때 이어짐)."""
    _write(V039)
    config.save_dorcha({"enabled": False})
    config.save_boss_pattern({"showUpcoming": False})
    raw = config._read_local_config()
    assert raw["autofind"] == V039["autofind"]
    assert raw["bossPattern"]["use"] is True and raw["haloTimer"]["use"] is True
    assert raw["dorcha"]["enabled"] is False and raw["dorcha"]["box"] == X


def test_boss_moved_to_remembered_only_shows_as_no_region():
    """0.39.0에서 보스바를 쓰는 기능을 모두 꺼서 보스 영역이 '기억한 위치'로만 옮겨진 사용자 —
    되돌린 버전에서는 영역 없음(보스 패턴 꺼짐과 같음)으로 보이는 게 맞다. 기억한 위치는 지우지 않는다."""
    raw = deepcopy(V039)
    raw["bossPattern"] = {"use": False, "box": None}
    raw["haloTimer"] = {"use": False, "box": None}
    raw["debuffTracker"] = {"use": False, "captureRegion": None}
    _write(raw)
    assert config.load_boss_bar_region() is None
    assert config._read_local_config()["autofind"]["found"]["boss"]["box"] == B


def test_boss_off_but_shared_bar_kept_reads_as_registered():
    """주의(0.38.1에 없는 상태): 0.39.0에서 보스 패턴만 끄고(use=False) 헤일로·디버프가 보스바를 계속 쓰면 영역이 남는다.
    0.38.1 코드는 use를 모르므로 영역이 있으면 보스 패턴 경고가 다시 동작한다(되돌린 버전의 알려진 차이)."""
    raw = deepcopy(V039)
    raw["bossPattern"] = {"use": False, "box": B}
    _write(raw)
    assert config.load_boss_bar_region() == B


@pytest.fixture
def window_with_039_config(monkeypatch):
    from PySide6.QtCore import QRect, QTimer
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui.main_window import MainWindow
    _write(V039)
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, 'quit', lambda: None)
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': 'test', 'name': '테스트'})
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, 'availableGeometry', lambda self: QRect(0, 0, 1600, 1100))
    monkeypatch.setattr(screen, 'geometry', lambda self: QRect(0, 0, 1600, 1100))
    w = MainWindow()
    w._post_show_done = True
    w.show()
    for timer in w.findChildren(QTimer):
        timer.stop()
    app.processEvents()
    yield w
    w._force_quit = True
    w.close()
    app.processEvents()


def test_app_starts_with_039_config_and_keeps_regions(window_with_039_config):
    w = window_with_039_config
    assert w.boss_tab._region == B
    assert w.boss_tab.halo_capture._region == H
    assert w.dorcha_tab._region == X and w.dorcha_tab._cfg["enabled"] is True
    assert config._read_local_config()["autofind"] == V039["autofind"]  # 시작해도 0.39.0 값을 지우지 않음
