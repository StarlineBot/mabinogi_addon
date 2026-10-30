"""0.29.0(안내·도움말 명세 14절): 색 이름 8가지·탭 단계 색·안내 회색·~해요 말투·기능 켜기 스위치·FPS 한 구역."""
import ast
from pathlib import Path

from PySide6.QtWidgets import QGroupBox

from mabinogi_addon.ui import palette
from mabinogi_addon.ui.palette import COLORS, Named, color
from mabinogi_addon.ui.widgets import SwitchButton
from test_navigation import window  # noqa: F401  (픽스처)

UI = Path(__file__).resolve().parents[1] / "src" / "mabinogi_addon" / "ui"


def test_palette_has_eight_names_with_dark_and_light_values():
    assert list(COLORS) == ["accent", "on-accent", "accent-soft", "muted", "ok", "warn", "danger", "brand"]
    assert color("accent", dark=True) == "#00C9A2" and color("accent", dark=False) == "#00A884"
    assert color("warn", dark=True) == "#E67E22" and color("accent-soft", dark=False) == "#1F8A7A"
    names = Named({"x": "ok"})
    assert names["x"] == color("ok") and names.get("missing", "fallback") == "fallback"


def test_screen_code_uses_names_instead_of_merged_hex_values():
    """합쳐진 옛 값(명세 14.6 표)이 화면 코드에 다시 생기지 않게. 대상 밖: 게임 오버레이·메모 글씨 강조·홈 남색 배경."""
    merged = ["#00D1A7", "#00B894", "#1ABC9C", "#2DD4BF", "#5EEAD4", "#14B8A6", "#06281E", "#04201C",
              "#7D828B", "#9AA0AA", "#C7CCD4", "#9CA3AF", "#34D399", "#FBBF24", "#F59E0B", "#D98A1A",
              "#E74C3C", "#D35B58", "#E06C75", "#EF8585"]
    outside = {"memo_overlay.py", "frame_overlay.py", "blackbox_toast.py", "toast.py", "guide_figure.py",
               "markdown_highlighter.py", "palette.py"}
    found = [f"{path.name}: {value}" for path in UI.glob("*.py") if path.name not in outside
             for value in merged if value.lower() in path.read_text(encoding="utf-8").lower()]
    assert found == []


def test_second_level_tab_is_soft_mint_and_third_stays_gray(window):
    from mabinogi_addon.ui.main_window import _subtab_qss, _tertiary_qss
    for dark in (True, False):
        second, third = _subtab_qss(dark), _tertiary_qss(dark)
        assert f"QTabBar::tab:selected {{ color: {color('accent-soft', dark)}" in second
        assert palette.subtab_underline(dark) in second
        assert color("accent-soft", dark) not in third  # 3단은 2단 색을 물려받지 않는다
    w, app = window
    assert w.boss_tab.pattern_tabs.styleSheet()  # 3단 스타일을 따로 지정


def test_region_guides_are_gray_hints(window):
    w, app = window
    from PySide6.QtWidgets import QLabel
    for root, text in ((w.boss_tab.halo_capture, "게임 상단의 남은 시간이"), (w.resource_tab, "보라색 원과 오른쪽 아래의")):
        label = next(child for child in root.findChildren(QLabel) if child.text().startswith(text))
        assert color("muted") in label.styleSheet()


def test_visible_ui_strings_use_haeyo_tone():
    """사용자에게 보이는 문구는 ~해요(명세 14.3). 문서 문자열·로그·예외 문구는 대상 밖."""
    logs = {"debug", "info", "warning", "error", "exception", "critical"}
    left = []
    for path in sorted(UI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body \
                    and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                skip.add(id(node.body[0].value))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in logs) \
                    or isinstance(node, ast.Raise):
                skip.update(id(child) for child in ast.walk(node))
        left += [f"{path.name}:{node.lineno}" for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str) and "니다" in node.value
                 and id(node) not in skip]
    assert left == []


def test_feature_on_off_controls_are_switches(window):
    w, app = window
    switches = {"custom": w.custom_overlay_tab.enable, "dorcha": w.dorcha_tab.enable, "tuarim": w.tuarim_tab.enable,
                "stat": w.stat_bars_tab.show_switch, "opt": w.optimization_tools.panel.auto,
                "fps": w.optimization_tools.panel.frames_toggle}
    if w.blackbox_tools.panel is not None:
        switches["blackbox"] = w.blackbox_tools.panel.enabled
    for name, control in switches.items():
        assert isinstance(control, SwitchButton), name
    assert w.optimization_tools.panel.auto.text() == "최적화 사용"
    assert not isinstance(w.optimization_tools.panel.toggle, SwitchButton)  # '추천 설정으로 최적화'는 버튼 유지
    assert not isinstance(w.stat_bars_tab.lock_btn, SwitchButton)  # 잠금은 상태 버튼 그대로


def test_stat_bar_switch_matches_home_and_bar_checks(window):
    w, app = window
    tab = w.stat_bars_tab
    tab.show_switch.click()
    assert not tab.any_shown() and not tab.show_switch.isChecked()
    w._show_home()
    assert w._home_state()["rows"]["stat_bars"][2] is False  # 홈 스위치와 같은 값
    w._home_switch("stat_bars", True)
    assert tab.show_switch.isChecked() and tab.any_shown()
    for check in tab._show_checks.values():
        check.setChecked(False)
    assert not tab.show_switch.isChecked()  # 바를 모두 끄면 스위치도 꺼짐


def test_optimization_switch_off_restores_like_home(window, monkeypatch):
    w, app = window
    tools = w.optimization_tools
    restores = []
    monkeypatch.setattr(tools, "_auto_start", lambda: False)
    monkeypatch.setattr(tools, "_toggle_optimization", lambda *a: restores.append(True))
    tools.panel.auto.click()
    assert tools.panel.auto.isChecked() and tools.home_state()[2] is True
    monkeypatch.setattr(tools, "_optimization_on", lambda: True)
    tools.panel.auto.click()  # 탭 스위치를 끄면 C안: 지금 적용분 원복
    assert not tools.panel.auto.isChecked() and restores == [True]


def test_fps_is_one_section_with_lock_on_the_right(window):
    w, app = window
    panel = w.optimization_tools.panel
    page = panel.tabs.widget(1)
    titles = [box.title() for box in page.findChildren(QGroupBox)]
    assert "게임에 FPS 표시" in titles and "오버레이" not in titles and "상태 · 수집 품질" not in titles
    w._tabs.setCurrentWidget(panel)
    panel.tabs.setCurrentIndex(1)
    app.processEvents()
    assert panel.lock.mapTo(page, panel.lock.rect().topLeft()).x() > panel.scale.mapTo(page, panel.scale.rect().topLeft()).x()
    assert "꺼짐 — 켜면 게임 화면에 FPS를 보여줘요" in panel.frames_status.text()
    assert panel.collect_toggle.text() == "진단 · 프레임 수집(구간 요약 파일)"


def test_home_warning_uses_the_same_orange_as_tabs():
    from mabinogi_addon.ui import home_page
    assert home_page.KIND_COLORS["warn"] == color("warn", dark=True)
    assert not hasattr(home_page, "YELLOW")
