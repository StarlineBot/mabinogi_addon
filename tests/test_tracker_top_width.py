"""버프·디버프 위 1줄(명세 17절)이 제작자·자동 찾기 v2 켬에서도 탭을 넓히지 않는다 — QA 50a07f9(최소 폭 936px).

머리 줄의 자동 찾기 표시는 짧게 '자동'·'직접 지정 · [자동으로 돌아가기]'(긴 설명은 툴팁), 상태 문구는 넘치면 '…' + 툴팁.
다른 화면의 자동 찾기 줄은 긴 한 줄.
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


@pytest.mark.parametrize("fixed", [False, True])
@pytest.mark.parametrize("kind", ["buff", "debuff"])
def test_creator_v2_header_keeps_tab_within_790(app, monkeypatch, kind, fixed):
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui.buff_tab import BuffTab
    from mabinogi_addon.ui.debuff_tab import DebuffTab
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)
    tab = BuffTab() if kind == "buff" else DebuffTab()
    try:
        autofind_regions.set_region(kind, {"x": 1, "y": 2, "w": 300, "h": 80})
        tab.region_section.set_autofind_key(kind)
        badge = tab.region_section.auto_badge
        assert badge.text() == "자동" and "자동으로 찾은 자리" in badge.toolTip()  # 긴 설명은 툴팁
        if fixed:  # 직접 지정 고정: '직접 지정 · [자동으로 돌아가기]'(first-use-v3 4.1)
            autofind_regions.user_set(kind)
            tab.region_section.refresh_autofind()
            assert badge.text() == "직접 지정 ·" and not tab.region_section.auto_return.isHidden()
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
    assert section.auto_badge.text() == "자동으로 찾은 자리로 읽어요"  # 도르카·투아림 등은 긴 한 줄
    assert section.auto_return.isHidden()
    autofind_regions.user_set("dorcha")
    section.refresh_autofind()
    assert section.auto_badge.text().startswith("직접 지정") and not section.auto_return.isHidden()
    section.auto_return.click()  # 자동으로 돌아가기
    assert not autofind_regions.is_fixed("dorcha") and section.auto_return.isHidden()
