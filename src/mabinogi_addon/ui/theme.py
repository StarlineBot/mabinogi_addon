"""앱 테마(색 구성표) 전환.

Qt 6.8+의 QStyleHints.setColorScheme로 앱 전체를 시스템/라이트/다크로 강제한다.
'시스템'(Unknown)이면 OS 설정을 따른다. 표준 위젯·팔레트는 즉시 바뀌고, 일부
하드코딩 색(오버레이 등)은 영향 적음. 설정값은 config의 theme(system/light/dark).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

_SCHEMES = {
    "system": Qt.ColorScheme.Unknown,
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
}

THEMES = ("system", "light", "dark")
THEME_LABELS = {"system": "시스템", "light": "라이트", "dark": "다크"}


def apply_theme(name: str) -> None:
    """선택한 테마를 앱 전체에 적용. 알 수 없는 값은 '시스템'으로."""
    scheme = _SCHEMES.get(name, Qt.ColorScheme.Unknown)
    hints = QGuiApplication.styleHints()
    if hints is not None:
        hints.setColorScheme(scheme)


def is_dark() -> bool:
    """현재 '실제로 적용 중'인 테마가 다크인지. 시스템(Unknown)이면 OS 설정 반영."""
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
        from PySide6.QtGui import QPalette

        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    return True
