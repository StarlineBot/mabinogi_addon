"""Claude Code Stop 훅 — 영어로 답하면 응답 종료를 막는다(사용자 지시 11-27 '앞으로 모든 세션에서 영어는 금지').

마지막 사용자 메시지 뒤 에이전트가 쓴 글(중간 진행 알림 포함)에서 코드 블록·인라인 코드·URL·파일 경로를 뺀 뒤,
1) 한글 없이 영어 낱말이 5개 이상인 줄이 하나라도 있거나
2) 남은 글자 중 영문자가 한글보다 많으면
막고 한국어로 다시 쓰게 한다. stop_hook_active여도 막는다 — 한국어로 쓰면 풀리므로 무한 반복되지 않는다.
훅이 실패하면 막지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _is_user_turn(row: dict) -> bool:
    if row.get('type') != 'user':
        return False
    content = row.get('message', {}).get('content')
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(c.get('type') == 'text' for c in content)


def last_reply(transcript: Path) -> str:
    rows = [json.loads(line) for line in transcript.read_text(encoding='utf-8').splitlines() if line.strip()]
    texts: list[str] = []
    for row in reversed(rows):
        if _is_user_turn(row):
            break
        if row.get('type') == 'assistant':
            for c in row.get('message', {}).get('content') or []:
                if isinstance(c, dict) and c.get('type') == 'text':
                    texts.append(c.get('text', ''))
    return '\n'.join(reversed(texts))


HANGUL = re.compile(r'[가-힣ㄱ-ㆎ]')
LATIN = re.compile(r'[A-Za-z]')
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]+")


def _clean(text: str) -> str:
    text = re.sub(r'```.*?```', '', text, flags=re.S)          # 코드 블록
    text = re.sub(r'`[^`]*`', '', text)                         # 인라인 코드(명령·경로·이름)
    text = re.sub(r'https?://\S+', '', text)                    # 주소
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)        # 링크는 글자만
    text = re.sub(r'(?<!\w)[\w.\-]*[/\\][\w./\\\-가-힣]+', '', text)  # 파일 경로
    return text


def english_lines(text: str) -> list[str]:
    out = []
    for line in _clean(text).splitlines():
        if HANGUL.search(line):
            continue
        if len(WORD.findall(line)) >= 5:
            out.append(line.strip()[:80])
    return out


def mostly_english(text: str) -> bool:
    t = _clean(text)
    h, l = len(HANGUL.findall(t)), len(LATIN.findall(t))
    return l >= 40 and l > h


def main() -> int:
    try:
        data = json.load(sys.stdin)
        reply = last_reply(Path(data['transcript_path']))
        lines = english_lines(reply)
        bad = bool(lines) or mostly_english(reply)
    except Exception:
        return 0
    if not bad:
        return 0
    sample = ('\n- ' + '\n- '.join(lines[:3])) if lines else ''
    print(
        '영어로 쓴 답이 있습니다 — 프로젝트 훅 .claude/hooks/korean_guard.py (사용자 지시 11-27: 모든 세션에서 영어 금지).\n'
        '중간 진행 알림을 포함해 사용자에게 보이는 글은 전부 한국어로 다시 쓰세요(명령·경로·코드 이름은 `백틱` 안에 두면 됩니다).'
        + sample,
        file=sys.stderr,
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
