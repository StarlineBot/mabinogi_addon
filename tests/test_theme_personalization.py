"""테마 개인화(테마 개인화 명세 2~6절): 진입·패널·직접 고르기 연동·즉시 다시 칠하기·저장·홈 틀/내용 칸."""
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from mabinogi_addon import config
from mabinogi_addon.theme_colors import DEFAULT, compute
from mabinogi_addon.ui import palette
from mabinogi_addon.ui.theme_panel import ADJUSTED_TEXT, ColorPickerDialog
from test_navigation import window  # noqa: F401  (픽스처)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def restore_theme():
    yield
    from mabinogi_addon.ui.theme import apply_theme
    apply_theme("system")  # 다른 테스트에 개인화 팔레트가 남지 않게


def _hint(w):
    return next(label for label in w.boss_tab.halo_capture.findChildren(QLabel)
                if label.text().startswith("게임 상단의 남은 시간이"))


def test_custom_is_fourth_theme_and_panel_opens_only_for_it(window):
    w, app = window
    settings = w.settings_tab
    assert list(settings._theme_btns) == ["system", "light", "dark", "custom"]
    assert "qconicalgradient" in settings._theme_btns["custom"].styleSheet()  # 무지개 동그라미
    settings._on_theme_pick("dark")
    assert settings.custom_panel.isHidden() and palette.custom() is None
    settings._on_theme_pick("custom")
    assert not settings.custom_panel.isHidden() and palette.custom() is not None
    assert config.load_theme() == "custom"


def test_switching_themes_repaints_named_colors_immediately(window):
    w, app = window
    settings = w.settings_tab
    settings._on_theme_pick("dark")
    assert palette.color("muted") in _hint(w).styleSheet()
    settings.custom_panel._set_all({"background": "#A5D8FF", "accent": "#A78BFA", "content": "auto"})
    custom = palette.custom()
    assert custom["tone"] == "light"
    assert custom["names"]["muted"] in _hint(w).styleSheet()  # 재시작 없이 바로
    assert custom["frame"] in w.centralWidget().styleSheet()  # 틀 = 고른 배경 그대로
    assert w.home_page.__class__.__module__ and __import__("mabinogi_addon.ui.home_page", fromlist=["_D"])._D["bg_top"] == custom["frame"]
    settings._on_theme_pick("dark")
    # 오프스크린은 색 구성표를 무시해 '다크'에서도 라이트 값일 수 있어, 지금 테마의 이름 값으로 확인
    assert palette.custom() is None and palette.color("muted") in _hint(w).styleSheet() and w.centralWidget().styleSheet() == ""
    assert config.load_custom_theme()["background"] == "#A5D8FF"  # 다른 테마로 바꿔도 개인화 값은 남김
    settings._on_theme_pick("custom")
    assert settings.custom_panel.values["background"] == "#A5D8FF"  # 다시 고르면 그대로 복원


def test_presets_tone_and_reset_save_at_once(window):
    w, app = window
    settings = w.settings_tab
    settings._on_theme_pick("custom")
    panel = settings.custom_panel
    panel._swatches["background"][3].click()  # 진한 핑크
    panel._swatches["accent"][1].click()  # 하늘
    panel.tone_buttons["light"].click()
    assert config.load_custom_theme() == {"background": "#C2185B", "accent": "#38BDF8", "content": "light"}
    assert palette.custom()["tone"] == "light"
    assert panel._swatches["background"][3].text() == "✓"
    panel.reset_btn.click()
    assert config.load_custom_theme() == DEFAULT
    assert palette.custom()["names"] == compute(**DEFAULT)["names"]  # 되돌리기 = 다크 테마와 같은 이름 색


def test_picker_fields_stay_in_sync_and_bad_code_keeps_value(app):
    dialog = ColorPickerDialog("배경 직접 고르기", "#C2185B")
    seen = []
    dialog.color_changed.connect(seen.append)
    assert dialog.hex_edit.text() == "#C2185B" and [s.value() for s in dialog.rgb.values()] == [194, 24, 91]
    dialog.rgb["G"].setValue(100)
    assert dialog.hex_edit.text() == "#C2645B" and seen[-1] == "#C2645B"
    dialog.hex_edit.setText("#123456")
    dialog.hex_edit.editingFinished.emit()
    assert [s.value() for s in dialog.rgb.values()] == [0x12, 0x34, 0x56] and dialog.value() == "#123456"
    dialog.hex_edit.setText("#zz")
    dialog.hex_edit.editingFinished.emit()
    assert dialog.value() == "#123456" and dialog.hex_edit.text() == "#123456"  # 잘못된 색 코드는 직전 값
    dialog._from_square(0.0, 1.0)  # 진하기 0·밝기 1 → 흰색(밝기 제한 없음)
    assert dialog.value() == "#FFFFFF"
    dialog._from_square(0.0, 0.0)
    assert dialog.value() == "#000000"
    dialog.set_adjusted(True)
    assert dialog.adjusted.text() == ADJUSTED_TEXT
    dialog.deleteLater()


def test_picker_previews_and_cancel_restores(window, monkeypatch):
    w, app = window
    settings = w.settings_tab
    settings._on_theme_pick("custom")
    panel = settings.custom_panel
    panel._set_all({"background": "#141A26", "accent": "#38BDF8", "content": "auto"})

    def run(dialog):
        dialog.hex_edit.setText("#F5EFE3")
        dialog.hex_edit.editingFinished.emit()
        assert palette.custom()["background"] == "#F5EFE3"  # 고르는 동안 미리 적용
        assert config.load_custom_theme()["background"] == "#141A26"  # 저장은 아직
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(ColorPickerDialog, "exec", run)
    panel.open_picker("background")
    assert palette.custom()["background"] == "#141A26"  # 취소 = 열기 전 값
    monkeypatch.setattr(ColorPickerDialog, "exec", lambda d: (d.hex_edit.setText("#808080"), d.hex_edit.editingFinished.emit(),
                                                              QDialog.DialogCode.Accepted)[-1])
    panel.open_picker("background")
    assert config.load_custom_theme()["background"] == "#808080" and panel._pick["background"].text() == "✓"


def test_bad_saved_values_read_as_defaults():
    raw = config._read_local_config()
    raw["customTheme"] = {"background": "nope", "accent": 42, "content": "sideways"}
    raw["theme"] = "custom"
    config._write_local_config(raw)
    assert config.load_custom_theme() == DEFAULT and config.load_theme() == "custom"


def test_dark_and_light_paths_do_not_use_custom_values(window):
    from mabinogi_addon.ui.main_window import _tab_qss
    w, app = window
    w.settings_tab._on_theme_pick("dark")
    assert palette.custom() is None and "#00C9A2" in _tab_qss(True)
    assert QApplication.instance().palette() is not None
