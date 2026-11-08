"""버프·디버프 위 1줄(명세 17절)이 제작자·자동 찾기 v2 켬에서도 탭을 넓히지 않는다 — QA 50a07f9(최소 폭 936px).

머리 줄의 v2 표시는 짧게 '자동(v2)'(긴 설명은 툴팁), 상태 문구는 넘치면 '…' + 툴팁. 다른 화면의 v2 줄은 그대로.
"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mabinogi_addon import autofind_regions, config  # noqa: E402

LONGEST = {"buff": "기준 버프 미검출 — 영역에 ⚓ 프리미엄 배틀 멤버십이 보이나요?",
           "debuff": "영역 미지정 — 디버프 판독 영역의 '직접 지정'을 먼저 하세요"}


@pytest.fixture
def app(monkeypatch):
    from PySide6.QtWidgets import QApplication
    store = {"buffTracker": {"captureRegion": {"x": 1, "y": 2, "w": 240, "h": 600}},
             "debuffTracker": {"captureRegion": {"x": 1, "y": 2, "w": 521, "h": 88}}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: json.loads(json.dumps(store)))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: (store.clear(), store.update(data)))
    autofind_regions.reset_for_tests()
    autofind_regions.activate(True)
    autofind_regions.set_use_values({k: True for k in autofind_regions.USE_KEYS})
    yield QApplication.instance() or QApplication([])
    autofind_regions.reset_for_tests()


@pytest.mark.parametrize("kind", ["buff", "debuff"])
def test_creator_v2_header_keeps_tab_within_790(app, monkeypatch, kind):
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui.buff_tab import BuffTab
    from mabinogi_addon.ui.debuff_tab import DebuffTab
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)
    tab = BuffTab() if kind == "buff" else DebuffTab()
    try:
        autofind_regions.set_region(kind, {"x": 1, "y": 2, "w": 300, "h": 80})
        tab.region_section.set_autofind_key(kind)
        badge = tab.region_section.auto_badge
        assert badge.text() == "자동(v2)" and "저장된 영역은 그대로" in badge.toolTip()  # 긴 설명은 툴팁
        tab.set_status(LONGEST[kind], "#e0a000")
        tab.resize(790, 760)
        tab.show()
        for _ in range(3):
            app.processEvents()
        tab.fit_width(790)
        app.processEvents()
        assert tab.minimumSizeHint().width() <= 790, tab.minimumSizeHint()
        assert not tab._columns.stacked
        assert tab.status_label.text() == LONGEST[kind]  # 문구 자체는 그대로(보일 때 넘치면 '…' + 툴팁)
        assert tab.region_section.toggle.isVisible() and tab.region_section.toggle.geometry().right() <= tab.width()
        tab.status_label.resize(60, tab.status_label.height())  # 아주 좁으면 말줄임 + 툴팁
        assert tab.status_label.toolTip() == LONGEST[kind]
    finally:
        tab.close()


def test_other_screens_keep_long_v2_line(app):
    from mabinogi_addon.ui.region_section import RegionSection
    from PySide6.QtWidgets import QWidget
    section = RegionSection(QWidget(), unset_text="x")
    section.set_registered(True)
    autofind_regions.set_region("dorcha", {"x": 1, "y": 2, "w": 30, "h": 10})
    section.set_autofind_key("dorcha")
    assert section.auto_badge.text().startswith("자동(v2) · ")  # 도르카·투아림 등은 지금처럼 긴 줄
