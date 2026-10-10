"""보스 패턴 경고 오버레이: 위치 이동(해제) / 경고 표시(고정)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.pattern_overlay import PatternWarningOverlay


def _app():
    return QApplication.instance() or QApplication([])


def test_unlocked_shows_sample_and_ignores_real_message():
    _app()
    o = PatternWarningOverlay()
    o.set_locked(False)  # 위치 조정 모드
    assert o.locked is False
    assert o.isVisible()  # 샘플이 떠서 끌어 옮길 수 있음
    o.show_message("보스 50% 패턴 임박", 1000)
    assert o._text != "보스 50% 패턴 임박"  # 실제 경고는 무시(샘플 유지)


def test_locked_shows_message_then_hides():
    _app()
    o = PatternWarningOverlay()
    o.set_locked(True)
    assert not o.isVisible()  # 고정+대기 → 숨김
    o.show_message("보스 50% 패턴 임박", 1000)
    assert o.isVisible() and o._text == "보스 50% 패턴 임박"
    o._on_timeout()  # 지속시간 종료
    assert not o.isVisible()
