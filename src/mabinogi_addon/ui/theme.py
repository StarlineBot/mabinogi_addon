"""앱 테마(색 구성표) 전환.

Qt 6.8+의 QStyleHints.setColorScheme로 앱 전체를 시스템/라이트/다크로 강제한다.
'시스템'(Unknown)이면 OS 설정을 따른다. 설정값은 config의 theme(system/light/dark/custom).

custom(테마 개인화 명세): theme_colors.compute로 틀·내용 칸·이름 색을 계산해
- 색 구성표는 내용 칸 톤(다크/라이트)으로 두고(기존 다크·라이트 처리 경로 그대로),
- 앱 팔레트의 바탕 색만 내용 칸 색으로 덮어쓰며,
- palette.color()가 개인화 값을 돌려주게 한다. 다른 테마로 돌아가면 팔레트를 기본으로 되돌린다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from . import palette

_SCHEMES = {
    "system": Qt.ColorScheme.Unknown,
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
}

THEMES = ("system", "light", "dark", "custom")
THEME_LABELS = {"system": "시스템", "light": "라이트", "dark": "다크", "custom": "개인화"}
_palette_overridden = False


def apply_theme(name: str, custom_values: dict | None = None) -> None:
    """선택한 테마를 앱 전체에 적용. 알 수 없는 값은 '시스템'으로.

    custom_values: 개인화 미리보기 값({background, accent, content}). 없으면 저장값.
    """
    global _palette_overridden
    hints = QGuiApplication.styleHints()
    app = QGuiApplication.instance()
    if name == "custom":
        from .. import config
        from ..theme_colors import compute
        values = custom_values or config.load_custom_theme()
        result = compute(values.get("background"), values.get("accent"), values.get("content", "auto"))
        palette.set_custom(result)
        if hints is not None:
            hints.setColorScheme(Qt.ColorScheme.Dark if result["tone"] == "dark" else Qt.ColorScheme.Light)
        if app is not None:
            app.setPalette(content_palette(result))
            _palette_overridden = True
        return
    palette.set_custom(None)
    if app is not None and _palette_overridden:
        app.setPalette(QPalette())  # 기본(플랫폼) 팔레트로 되돌림 — 색 구성표를 다시 따른다
        _palette_overridden = False
    if hints is not None:
        hints.setColorScheme(_SCHEMES.get(name, Qt.ColorScheme.Unknown))


def content_palette(result: dict) -> QPalette:
    """개인화 내용 칸 팔레트: 입력칸·버튼·테두리·구분선은 바탕에서 밝기를 옮긴 단계 색."""
    roles = result["roles"]
    pal = QPalette()
    R = QPalette.ColorRole
    for role, key in ((R.Window, "window"), (R.Base, "base"), (R.AlternateBase, "alternate"), (R.Button, "button"),
                      (R.Midlight, "midlight"), (R.Mid, "mid"), (R.Dark, "dark"), (R.Light, "light"),
                      (R.WindowText, "text"), (R.Text, "text"), (R.ButtonText, "text"), (R.ToolTipBase, "base"),
                      (R.ToolTipText, "text")):
        pal.setColor(role, QColor(roles[key]))
    pal.setColor(R.PlaceholderText, QColor(result["names"]["muted"]))
    pal.setColor(R.Highlight, QColor(result["names"]["accent"]))
    pal.setColor(R.HighlightedText, QColor(result["names"]["on-accent"]))
    pal.setColor(R.Link, QColor(result["names"]["accent"]))
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(roles["disabled"]))
    return pal


def is_dark() -> bool:
    """현재 '실제로 적용 중'인 테마가 다크인지. 시스템(Unknown)이면 OS 설정 반영. 개인화면 내용 칸 톤."""
    custom = palette.custom()
    if custom is not None:
        return custom["tone"] == "dark"
    hints = QGuiApplication.styleHints()
    try:
        scheme = hints.colorScheme() if hints is not None else None
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:  # noqa: BLE001, S110 — 구버전/플랫폼차 → 팔레트로 폴백
        pass
    app = QGuiApplication.instance()
    if app is not None:
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    return True
