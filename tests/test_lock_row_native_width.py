"""0.31.1 QA: 버프·디버프 잠금 줄 '위치 잠금 │ 배율 │ 불투명도'가 실제 Windows 스타일·글꼴에서 790 창을 한 칸으로 접지 않는다.

0.31.0은 세 칸 모두의 최소 폭을 가장 넓은 칸 기본 폭으로 걸어(3배), Windows 11 스타일의 넓은 숫자 칸(가로 화살표)에서
왼쪽 최소 폭이 커져 TrackerColumns.fit_width가 두 칸 → 한 칸으로 접었다. 오프스크린(Fusion)으로는 재현되지 않아
windows.yml의 실제 Windows 실행(-m windows_integration)에서 확인한다. 배율 125·150%는 QT_SCALE_FACTOR로 새 프로세스.
"""
import os
import subprocess
import sys

import pytest

from test_navigation import window  # noqa: F401  (픽스처)

pytestmark = pytest.mark.windows_integration


def _check_tabs(w, app):
    for key in ("buff", "debuff"):
        w._open_setup_feature(key)
        for _ in range(4):
            app.processEvents()
        tab = getattr(w, key + "_tab")
        assert w.width() == 790
        assert not tab._columns.stacked, (key, w.height(), [x.width() for x in (tab.lock_btn, tab.scale_spin, tab.opacity_spin)])
        for widget in (tab.lock_btn, tab.scale_spin, tab.opacity_spin):  # 세 칸이 잘리지 않음
            assert widget.width() >= widget.minimumSizeHint().width(), (key, widget, widget.width())
        assert w._combat_pages[key].horizontalScrollBar().maximum() == 0


def test_buff_debuff_stay_two_columns_on_native_style(window):
    w, app = window
    for chat in (False, True):  # 잡담 꺼짐 800 / 켜짐 864 — 세로 스크롤 막대가 생기면 폭이 줄어든다
        w.creator_dialogue.set_enabled(chat)
        w.creator_dialogue.refresh()
        _check_tabs(w, app)


@pytest.mark.skipif(os.environ.get("MABINOGI_LOCK_ROW_CHILD") == "1", reason="배율 자식 프로세스 안에서는 다시 띄우지 않음")
@pytest.mark.parametrize("scale", ["1.25", "1.5"])
def test_buff_debuff_stay_two_columns_at_display_scale(scale):
    env = {**os.environ, "QT_SCALE_FACTOR": scale, "MABINOGI_LOCK_ROW_CHILD": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "windows_integration",
         f"{__file__}::test_buff_debuff_stay_two_columns_on_native_style"],
        env=env, capture_output=True, text=True, timeout=300, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
