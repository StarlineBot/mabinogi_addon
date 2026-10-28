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


def test_guide_stage_four_introduces_other_features_and_opens_optimization(window, monkeypatch):
    # 명세 auto-setup-v2 11절: 5단계(진행 표시는 제목 오른쪽 위), 4단계 = 최적화 강조 카드 + 그 밖의 기능 카드, 로그인 없음
    from mabinogi_addon.ui.setup_guide import OTHER_FEATURES
    w = window[0]
    monkeypatch.setattr(config, 'load_discord_user', lambda *a: None)
    w.optimization_tools.refresh_access()
    w._open_guide()
    guide = w.setup_guide
    guide.move(1); guide.move(1); guide.move(1)
    assert guide.stage == 3 and guide.title.text() == '다른 기능도 있어요'
    assert guide.step_label.text().startswith('<b>4 / 5</b>')
    assert guide.others.isVisible() and not guide.selection.isVisible() and not guide.later_btn.isVisible()
    assert [name for name, *_ in OTHER_FEATURES] == ['블랙박스', '파티 모집', '커스텀 오버레이', '메모', '계산기']
    assert not any('로그인' in b.text() for b in guide.findChildren(type(guide.next_btn)))
    guide.optimization_btn.click()
    assert w._pages.currentWidget() is w._tabs and w._tabs.currentWidget() is w.optimization_tools.panel
    assert guide.active and w._guide_return_btn.isVisible()  # 안내는 이어서 볼 수 있다
    w._guide_return_btn.click()
    assert guide.stage == 3
    guide.next_btn.click()  # 마지막 안내 단계에서 '다음' → 앱 둘러보기
    assert not guide.active and w._tour.isVisible()
    w._tour._finish()


def test_optimization_panel_is_not_a_fragment_before_it_joins_the_tabs(window):
    # 탭에 붙기 전 패널은 창의 자식이라, 숨기지 않으면 창이 보일 때 왼쪽 위(0,0)에 조각으로 함께 그려졌다
    from PySide6.QtWidgets import QWidget
    from mabinogi_addon.ui.optimization_controller import OptimizationController
    host = QWidget()  # 탭이 아직 없는 창(메인 창 구성 도중과 같은 상태)
    tools = OptimizationController(host)
    try:
        host.show()
        assert tools.panel.parentWidget() is host and not tools.panel.isVisible()
    finally:
        tools.prepare_close()
        host.close()


def test_party_keyword_bell_toggle_is_kept(window, monkeypatch):
    # 2026-10-28 사용자 결정: 종(🔔/🔕)이 직관적이라 '소리 알림' 체크로 바꾸지 않고 유지
    from mabinogi_addon.ui import party_tab
    tab = window[0].party_tab
    monkeypatch.setattr(party_tab, 'show_toast', lambda *a, **k: None)
    monkeypatch.setattr(party_tab.config, 'save_party_alert_sound', lambda *a: None)
    monkeypatch.setattr(tab._sound, 'play', lambda *a: None)
    before = tab._alert_sound
    assert tab.alert_bell.text() == ('🔔' if before else '🔕')
    tab.alert_bell.click()
    assert tab._alert_sound is (not before) and tab.alert_bell.text() == ('🔔' if not before else '🔕')
    assert not hasattr(tab, 'alert_sound_chk')
