"""버그 신고 진단 헤더 + 로그 버퍼(DEBUG 캡처) 테스트."""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon import diagnostics, logbuffer


@pytest.fixture(scope="module")
def _app():
    return QApplication.instance() or QApplication([])


def test_header_has_key_fields(_app) -> None:
    text = diagnostics.header_text()
    for key in ("앱 버전", "빌드", "OS", "버프 영역", "디버프 영역", "투아림 영역"):
        assert key in text


def test_logbuffer_captures_debug() -> None:
    handler = logbuffer.install()
    root = logging.getLogger()
    prev = root.level
    root.setLevel(logging.DEBUG)
    try:
        logging.getLogger("mabinogi_addon.test").debug("디버그-표식-12345")
        assert "디버그-표식-12345" in logbuffer.recent_logs()
    finally:
        root.setLevel(prev)
        _ = handler  # 설치 핸들러 참조(미사용 경고 방지)
