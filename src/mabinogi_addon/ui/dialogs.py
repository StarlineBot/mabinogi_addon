"""확인 창 표준 버튼 한글화(QA 0.29.0): Yes/No/OK/Cancel → 예/아니요/확인/취소.

Qt는 표준 버튼 글자를 QCoreApplication.translate("QPlatformTheme", "&Yes") 식으로 묻는다.
번역 파일(qtbase_ko) 대신 코드로 된 번역기 하나를 앱에 설치해 그 질문에만 우리 글자로 답한다.
- QMessageBox.question/information/warning 같은 정적 함수와 직접 만든 QMessageBox 모두 한 번에 바뀐다.
- 단축키 표시('예(&Y)')가 붙지 않고, exe에 번역 파일을 따로 넣지 않아도 된다.
- 직접 글자를 넣은 버튼(setup_flow의 '이 영역으로 등록' 등)은 setText가 이겨서 그대로다.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QTranslator

BUTTON_TEXT = {
    "&Yes": "예", "&No": "아니요", "OK": "확인", "Cancel": "취소", "Close": "닫기",
    "Save": "저장", "Save All": "모두 저장", "Discard": "저장 안 함", "Apply": "적용",
    "Reset": "초기화", "Restore Defaults": "기본값으로", "Open": "열기", "Help": "도움말",
    "Retry": "다시 시도", "Ignore": "무시", "Abort": "중단",
    "Yes to &All": "모두 예", "N&o to All": "모두 아니요",
}


class _ButtonTranslator(QTranslator):
    def translate(self, context, source, disambiguation=None, n=-1):  # noqa: ARG002 — Qt 시그니처
        if context == "QPlatformTheme" and source in BUTTON_TEXT:
            return BUTTON_TEXT[source]
        return super().translate(context, source, disambiguation, n)  # 모르는 글자는 원래대로


_installed: _ButtonTranslator | None = None


def install_korean_buttons(app: QCoreApplication | None = None) -> None:
    """앱에 한 번만 설치(여러 번 불러도 같다). 앱이 없으면 아무것도 하지 않는다."""
    global _installed
    app = app or QCoreApplication.instance()
    if app is None or _installed is not None:
        return
    _installed = _ButtonTranslator(app)  # 앱이 부모라 앱과 함께 산다
    app.installTranslator(_installed)
