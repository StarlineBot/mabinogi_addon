"""0.25.0 사용 기능 전체 공개(기능 공개 정책 7절): 로그인 없이 사용 기능 모두, 수집·진단만 제한 유지."""
from mabinogi_addon import config, feature_access, setup_state
from test_navigation import window  # noqa: F401  (픽스처)


def test_logged_out_user_gets_every_usage_feature(window, monkeypatch):
    w = window[0]
    monkeypatch.setattr(config, 'load_discord_user', lambda *a: None)
    assert feature_access.blackbox_available() and feature_access.optimization_available()
    assert all(setup_state.batch_allowed(f.key) for f in setup_state.FEATURES)  # 1분 헤일로 포함 일괄 자동설정
    w.optimization_tools.refresh_access(); w.blackbox_tools.refresh_access()
    names = [w._tabs.tabText(i) for i in range(w._tabs.count())]
    assert '최적화' in names and '블랙박스' in names
    halo = w.boss_tab.halo_capture
    halo._refresh()
    assert halo._allowed() and not halo.isHidden() and w.boss_tab.pattern_tabs.isTabVisible(1)
    w.debuff_tab.method_combo.setCurrentIndex(w.debuff_tab.method_combo.findData('percent'))
    assert w.debuff_tab.effective_gate_mode() == 'percent'  # 디버프 3차
    w.dorcha_tab._apply_gate()
    assert w.resource_tab.percent_chk.isHidden() is (not w.dorcha_tab._alpha_ready)  # 투아림 % 표시


def test_collection_and_diagnostics_stay_restricted_when_logged_out(window, monkeypatch):
    w = window[0]
    monkeypatch.setattr(config, 'load_discord_user', lambda *a: None)
    halo = w.boss_tab.halo_capture
    halo._refresh()
    assert not halo._collect_allowed() and not halo.disclosure.isVisible()  # 헤일로 수집: 제작자
    assert not w.optimization_tools._creator()  # FPS 수집 모드: 제작자
    w.settings_tab._refresh_login()
    assert '로그인하면 디스코드로 설정을 백업하고, 오류 신고용 수집 도구를 쓸 수 있어요.' in [
        label.text() for label in w.settings_tab.findChildren(type(w.settings_tab._login_status))]


def test_creator_dialogue_finds_settings_tab_by_widget_not_position(window, monkeypatch):
    # 공개로 블랙박스·최적화 탭이 늘어 설정 탭이 4번째가 아니게 됨 — 위치(3)로 판단하던 것을 위젯으로
    w = window[0]
    monkeypatch.setattr(config, 'load_discord_user', lambda *a: None)
    w.optimization_tools.refresh_access(); w.blackbox_tools.refresh_access()
    d = w.creator_dialogue
    w._tabs.setCurrentWidget(w.optimization_tools.panel)
    assert w._tabs.currentIndex() == 3 and d._footer_visible() and d._anchor() is d.face
    w._tabs.setCurrentWidget(w._settings_scroll)
    assert not d._footer_visible() and d._anchor() is w.settings_tab.creator_avatar
