"""업데이트 노트 파서/선택 로직 테스트.

RELEASE_NOTES_FILE 을 임시 파일로 바꿔치기해 notes_since 의 버전 선택 규칙만 본다.
(다이얼로그 렌더는 Qt 의존이라 여기선 로직만.)
"""

from pathlib import Path

import pytest

from mabinogi_addon.ui import release_notes

_SAMPLE = """\
## v0.3.21

최신 노트.

- 가
- 나

## v0.3.20

이전 노트.

## v0.3.19

더 이전.
"""


@pytest.fixture
def notes_file(tmp_path, monkeypatch):
    p = tmp_path / "release_notes.md"
    p.write_text(_SAMPLE, encoding="utf-8")
    monkeypatch.setattr(release_notes, "RELEASE_NOTES_FILE", p)
    return p


def test_first_run_shows_only_current(notes_file):
    out = release_notes.notes_since(None, "0.3.21")
    assert "최신 노트" in out
    assert "이전 노트" not in out  # 처음 실행이면 현재 버전만


def test_update_shows_range_newest_first(notes_file):
    out = release_notes.notes_since("0.3.19", "0.3.21")
    assert "최신 노트" in out and "이전 노트" in out
    assert "더 이전" not in out  # 0.3.19 는 '이후'가 아니므로 제외
    # 최신이 위로 정렬
    assert out.index("v0.3.21") < out.index("v0.3.20")


def test_same_version_shows_nothing(notes_file):
    assert release_notes.notes_since("0.3.21", "0.3.21") == ""


def test_future_notes_excluded(notes_file):
    # 현재가 0.3.20 이면 0.3.21(미래) 노트는 안 보이고 0.3.20 만.
    out = release_notes.notes_since("0.3.19", "0.3.20")
    assert "이전 노트" in out
    assert "최신 노트" not in out


def test_missing_section_returns_empty(notes_file):
    assert release_notes.notes_since(None, "9.9.9") == ""


def test_bundled_notes_file_parses():
    """실제 번들 노트 파일이 섹션으로 파싱되는지(형식 깨짐 방지)."""
    text = Path(release_notes.RELEASE_NOTES_FILE).read_text(encoding="utf-8")
    sections = release_notes._parse_sections(text)
    assert sections, "번들 release_notes.md 에 버전 섹션이 없음"
    assert all(body.strip() for _v, body in sections)
