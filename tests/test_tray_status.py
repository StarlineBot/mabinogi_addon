"""트레이에 블랙박스·최적화 상태 표시(2026-10-27 사용자 결정): 메뉴 맨 위 상태 줄·툴팁·최소화 알림."""
from types import SimpleNamespace as NS

from mabinogi_addon import config
from test_navigation import window  # noqa: F401  (픽스처)


def _show_badges(w, blackbox=None, optimization=None):
    for badge, state in ((w._blackbox_badge, blackbox), (w._optimization_badge, optimization)):
        if state is None:
            badge.hide()
        else:
            badge.setText('● ' + state[0]); badge.setStyleSheet(w.status_style(state[1])); badge.show()


def test_status_lines_follow_header_badges(window):
    w = window[0]
    _show_badges(w)
    assert w._tray_status_lines() == [('combat', '전투 보조: 켜짐', w._STATUS_OK)]
    _show_badges(w, ('블랙박스: 보관 중 3:12', '#2ecc71'), ('최적화: 게임 대기', '#8a8f98'))
    w.hide()  # 트레이로 숨겨도(창이 안 보여도) 배지 상태로 판단
    assert w._tray_status_lines() == [('combat', '전투 보조: 켜짐', w._STATUS_OK),
                                      ('blackbox', '블랙박스: 보관 중 3:12', '#2ecc71'),
                                      ('optimization', '최적화: 게임 대기', '#8a8f98')]


def test_menu_puts_status_lines_on_top_and_opens_tab(window, monkeypatch):
    w = window[0]
    menu = w._build_tray_menu()
    w._tray = NS(contextMenu=lambda: menu, setToolTip=lambda tip: None)
    _show_badges(w, ('블랙박스: 보관 중 3:12', '#2ecc71'), ('최적화: 적용 중', '#2ecc71'))
    w._refresh_tray_menu()
    texts = [a.text() for a in menu.actions()]
    assert texts[:3] == ['전투 보조: 켜짐', '블랙박스: 보관 중 3:12', '최적화: 적용 중'] and menu.actions()[3].isSeparator()
    assert texts[4:] == ['열기', '전투 보조 일시정지', '', '종료']
    assert not menu.actions()[0].icon().isNull() and 'margin-left:12px' in menu.styleSheet()
    _show_badges(w)
    w._refresh_tray_menu()  # 열 때마다 새로: 배지가 사라지면 줄도 사라짐
    assert [a.text() for a in menu.actions()][:2] == ['전투 보조: 켜짐', '']
    opened = []
    monkeypatch.setattr(w.optimization_tools, '_open_tab', lambda: opened.append('opt'))
    _show_badges(w, None, ('최적화: 적용 중', '#2ecc71'))
    w._refresh_tray_menu()
    menu.actions()[1].trigger()
    assert opened == ['opt']
    w._tray = None


def test_tooltip_lists_visible_status_lines(window):
    w = window[0]
    tips = []
    w._tray = NS(setToolTip=tips.append)
    _show_badges(w, ('블랙박스: 보관 중 1:00', '#2ecc71'))
    w._update_tray_tooltip(); w._update_tray_tooltip()
    assert tips == [f'{config.APP_NAME}\n전투 보조: 켜짐\n블랙박스: 보관 중 1:00']  # 바뀔 때만 설정
    w._tray = None


def test_minimized_message_mentions_only_what_keeps_running(window, monkeypatch):
    w = window[0]
    _show_badges(w)
    monkeypatch.setattr(w.blackbox_tools, 'service', None)
    assert w._tray_minimized_message() == '트레이로 최소화했어요.\n트레이 아이콘을 누르면 다시 열려요.'
    monkeypatch.setattr(w.blackbox_tools, 'service', NS(enabled=True))
    assert '블랙박스 보관은 계속 동작해요.' in w._tray_minimized_message()
    _show_badges(w, None, ('최적화: 적용 중', '#2ecc71'))
    assert '블랙박스 보관과 최적화는 계속 동작해요.' in w._tray_minimized_message()
    monkeypatch.setattr(w.blackbox_tools, 'service', None)
    assert '최적화는 계속 동작해요.' in w._tray_minimized_message()
