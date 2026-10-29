"""화면 마무리 다듬기(안내·도움말 명세 13절, 0.28.1): 잠금 버튼 통일·보스/헤일로 줄 맞춤·체력바·투아림 여백·단축바/메모 접기·잡담 항상 켬."""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QLabel, QPushButton

from mabinogi_addon import config
from mabinogi_addon.ui.settings_layout import lock_width
from test_navigation import window  # noqa: F401  (픽스처)

LOCK_TEXTS = {"위치 잠금", "위치 잠금됨", "전체 위치 잠금", "전체 위치 잠금됨"}


def _x(widget, root):
    return widget.mapTo(root, QPoint()).x()


def _locks(w):
    return {
        "buff": w.buff_tab.lock_btn, "debuff": w.debuff_tab.lock_btn,
        "boss_warn": w.boss_tab.warn_lock_btn, "boss_list": w.boss_tab.upcoming_lock_btn,
        "halo_warn": w.boss_tab.halo_capture.warn_lock, "halo_countdown": w.boss_tab.halo_capture.countdown_lock,
        "stat": w.stat_bars_tab.lock_btn, **{f"stat_{k}": b for k, b in w.stat_bars_tab.bar_lock_buttons.items()},
        "dorcha": w.dorcha_tab.lock_chk, "custom": w.custom_overlay_tab.lock_all_btn,
        "skillbar": w.skillbar_tab.lock_all_btn, "memo": w.memo_tab.lock_btn,
        "fps": w.optimization_tools.panel.lock,
    }


def test_lock_buttons_share_wording_and_fixed_width(window):
    w, app = window
    locks = _locks(w)
    width = lock_width(w.buff_tab.lock_btn)
    for name, button in locks.items():
        assert button.text() in LOCK_TEXTS, name
        assert button.minimumWidth() == button.maximumWidth() == width, name  # 앱 전체 같은 고정 폭
        assert button.text().startswith("전체 ") is (name in ("stat", "custom", "skillbar")), name
    probe = QPushButton("전체 위치 잠금됨")
    probe.setStyleSheet(locks["stat"].styleSheet())
    probe.ensurePolished()
    assert probe.sizeHint().width() <= width  # 가장 긴 글자가 들어간다


def test_boss_and_halo_rows_line_up(window):
    w, app = window
    w._open_setup_feature("boss")
    app.processEvents()
    boss = w.boss_tab
    assert boss.show_upcoming.text() == "표시"
    assert _x(boss.warn_lock_btn, boss) == _x(boss.upcoming_lock_btn, boss)  # 같은 세로선
    assert _x(boss.upcoming_lock_btn, boss) < _x(boss.show_upcoming, boss)  # 표시 체크는 잠금 뒤
    w._open_setup_feature("halo_timer")
    app.processEvents()
    halo = boss.halo_capture
    # 상자 안 두 줄은 같은 세로선. 화면끼리는 맞추지 않음(이름 길이가 달라 간격 통일 우선, 2026-10-29 사용자 결정)
    assert _x(halo.warn_lock, w) == _x(halo.countdown_lock, w)


def test_stat_bars_lock_menu_and_boss_note_first(window):
    w, app = window
    tab = w.stat_bars_tab
    assert tab.per_bar_toggle.text() == "생명력·마나·스태미나 따로 잠그기"
    tab._set_locked_all(True)
    assert tab.lock_btn.text() == "전체 위치 잠금됨"
    tab._set_bar_locked("mp", False)
    assert tab.lock_btn.text() == "전체 위치 잠금" and tab.bar_lock_buttons["hp"].text() == "위치 잠금됨"
    box = next(b for b in tab.findChildren(type(tab._alert_group())) if b.title() == "낮은 수치 알림 · 보스전")
    first = box.layout().itemAt(0).widget()
    assert first is not None and first.text() == "보스 체력바가 보일 때만 동작해요"


def test_tuarim_alert_row_has_no_inner_margin_and_second_follows_first(window):
    w, app = window
    w._open_setup_feature("tuarim")
    app.processEvents()
    box = w.tuarim_tab.threshold_box
    assert box.layout().contentsMargins().left() == 0
    first, second = w.tuarim_tab._spins
    gap = _x(second, box) - (_x(first, box) + first.width())
    assert gap < 160  # '추가 알림'이 가로 절반 지점으로 밀려나지 않는다(첫 알림 소리 체크 + 일정 간격)
    assert _x(second, box) < box.width() // 2


def test_skillbar_and_memo_fold_like_other_screens(window):
    w, app = window
    skill, memo = w.skillbar_tab, w.memo_tab
    assert not hasattr(skill, "unlock_all_btn")
    assert not skill.region_section.registered and not memo.region_section.registered
    assert memo.region_section.box.title() == "표시 위치 지정"
    skill._anchor = {"x": 10, "y": 20}
    skill._update_anchor_label()
    assert skill.region_section.registered and skill.region_section.summary_label.text() == "✓ 영역 지정됨"
    config.save_capture_region(100, 120, 300, 90, "memoTracker")
    memo._update_region_hint()
    assert memo.region_section.summary_label.text() == "✓ 표시 위치 지정됨"
    assert memo.region_section.toggle.text() == "표시 위치 다시 지정"
    assert not hasattr(memo, "lock_hint")  # 잠금 설명 줄 삭제
    skill._set_locked_all(True)
    assert skill.lock_all_btn.text() == "전체 위치 잠금됨" and skill.lock_all_btn.isChecked()
    skill._set_locked_all(False)
    assert skill.lock_all_btn.text() == "전체 위치 잠금"


def test_creator_dialogue_is_always_on_with_sound_choice_only(window):
    w, app = window
    config.save_general_flag("creatorDialogue", False)  # 예전에 끈 사용자도 켜진 것으로
    from mabinogi_addon.ui.settings_tab import SettingsTab
    tab = SettingsTab(w._watcher)
    try:
        assert tab.dialogue_enabled.isHidden() and tab.dialogue_enabled.isChecked()
        assert tab.dialogue_sound_enabled.isEnabled()
    finally:
        tab.deleteLater()




def _name_gap(root, label_text, button):
    label = next(child for child in root.findChildren(QLabel) if child.text() == label_text)
    return _x(button, root) - (_x(label, root) + label.fontMetrics().horizontalAdvance(label_text))


def test_name_column_gap_matches_other_screens(window):
    """0.28.1 사용자 피드백: 이름 칸을 고정 폭(96px)이나 다른 화면 이름에 맞추면 이름 뒤가 벌어졌다.
    상자마다 가장 긴 이름 뒤 간격이 다른 화면의 '라벨 + 조작' 간격(단축바 '표시 배율' 등)과 같아야 한다."""
    w, app = window
    w._open_setup_feature("skillbar")
    app.processEvents()
    reference = _name_gap(w.skillbar_tab, "표시 배율", w.skillbar_tab.scale_spin)
    w._open_setup_feature("boss")
    app.processEvents()
    boss = w.boss_tab
    assert min(_name_gap(boss, "패턴 경고", boss.warn_lock_btn), _name_gap(boss, "패턴 목록", boss.upcoming_lock_btn)) <= reference + 3
    w._open_setup_feature("halo_timer")
    app.processEvents()
    halo = boss.halo_capture
    gaps = (_name_gap(halo, "다음 헤일로", halo.countdown_lock), _name_gap(halo, "헤일로 경고", halo.warn_lock))
    assert min(gaps) <= reference + 3
