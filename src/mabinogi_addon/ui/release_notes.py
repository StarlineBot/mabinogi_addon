"""업데이트 노트(새 버전 첫 실행 시 안내).

번들 `assets/release_notes.md` 를 버전별 섹션(`## vX.Y.Z`)으로 쪼개, 사용자가
마지막으로 본 버전 이후의 노트만 모아 마크다운 다이얼로그로 보여준다.

호출 측(main_window)이 '마지막으로 본 버전(config)'과 현재 버전을 넘겨 판단한다.
커밋 메시지가 아니라, 사람이 읽을 수 있게 손으로 쓴 노트를 보여주는 게 목적.
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .. import paths

RELEASE_NOTES_FILE = paths.resource_dir() / "release_notes.md"

# "## v0.3.21" 같은 버전 헤더. v는 선택.
_HEADER = re.compile(r"^##\s+v?(\d+(?:\.\d+)*)\s*$", re.MULTILINE)


def _version_tuple(v: str) -> tuple[int, ...]:
    """'0.3.21' → (0,3,21). 비교용(정렬·초과 판정)."""
    out: list[int] = []
    for part in v.split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """마크다운을 [(버전, 본문), ...] 로. 파일에 적힌 순서(보통 최신 먼저)를 유지."""
    sections: list[tuple[str, str]] = []
    matches = list(_HEADER.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip()
        sections.append((m.group(1), body))
    return sections


def notes_since(last_seen: str | None, current: str) -> str:
    """last_seen(제외) ~ current(포함) 사이 버전들의 노트를 하나의 마크다운으로.

    - last_seen 이 None(처음 실행/기능 도입 전 사용자)이면 현재 버전 노트만.
    - 해당 섹션이 없으면 빈 문자열(→ 호출 측이 다이얼로그를 안 띄움).
    최신 버전이 위로 오도록 정렬해 합친다.
    """
    try:
        text = RELEASE_NOTES_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""
    sections = _parse_sections(text)
    if not sections:
        return ""
    cur = _version_tuple(current)
    low = _version_tuple(last_seen) if last_seen else None

    def _in_range(ver: str) -> bool:
        vt = _version_tuple(ver)
        if vt > cur:  # 현재 버전보다 미래 노트는 제외
            return False
        if low is None:  # 처음 실행 → 현재 버전 노트만
            return vt == cur
        return vt > low  # 마지막으로 본 버전 이후 전부

    picked = [(ver, body) for ver, body in sections if _in_range(ver)]
    picked.sort(key=lambda s: _version_tuple(s[0]), reverse=True)
    return "\n\n".join(f"## v{ver}\n\n{body}" for ver, body in picked).strip()


class ReleaseNotesDialog(QDialog):
    """업데이트 노트 마크다운을 읽기 전용으로 보여주는 창."""

    def __init__(self, markdown: str, version: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"업데이트 노트 · v{version}")
        self.setMinimumSize(560, 440)  # 기본 너비를 넓혀 문장이 덜 접히게
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 12)
        v.setSpacing(10)

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setMarkdown(markdown)
        # QTextBrowser 기본 리스트 들여쓰기가 과하게 넓다. 불릿 앞 여백을 줄인다.
        doc = body.document()
        doc.setIndentWidth(14)  # 리스트/인용 한 단계 들여쓰기 폭(기본보다 좁게)
        doc.setDocumentMargin(6)
        v.addWidget(body, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("확인")
        ok.setObjectName("notesOk")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)

        self.setStyleSheet(
            "#notesOk { background:#00B894; color:#06281e; border:none;"
            " border-radius:6px; padding:6px 18px; font-weight:700; }"
            "#notesOk:hover { background:#00D1A7; }"
        )
