"""Claude Code Stop 훅 — 사용자에게 결과를 알리는 마지막 답이 영어면 응답 종료를 막는다.

사용자 지시 11-27 '모든 세션에서 영어 금지' → 11-28 정정 '작업할 때는 영어로 해도 됨, 나한테 결과 알려줄 때만 한글로'.
그래서 마지막 도구 호출 뒤에 쓴 글(= 사용자에게 보내는 최종 답)만 본다. 작업 중 진행 알림·생각·도구 입력은 보지 않는다.
최종 답에서 코드 블록·인라인 코드·URL·파일 경로를 뺀 뒤,
1) 한글 없는 줄 중 '영어 문장'(영어 낱말 5개 이상 + the·is·and 같은 영어 기능어 2개 이상)이 하나라도 있거나
2) 글 전체가 영어 위주(영문자가 한글보다 많고 기능어 8개 이상)면
막고 한국어로 다시 쓰게 한다. main·verify-only·명령·파일 이름·식별자만 쓴 줄은 기능어가 없어 막지 않는다
(사용자 11-27 '영어로 피드백하는 걸 막는 것 — main·실행 명령어 같은 건 걸리지 않게'). stop_hook_active여도 막는다 — 한국어로 쓰면 풀리므로 무한 반복되지 않는다.
훅이 실패하면 막지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def last_reply(transcript: Path) -> str:
    """마지막 도구 호출(또는 사용자 메시지) 뒤 에이전트가 쓴 글 — 사용자에게 보내는 최종 답."""
    rows = [json.loads(line) for line in transcript.read_text(encoding='utf-8').splitlines() if line.strip()]
    texts: list[str] = []
    for row in reversed(rows):
        if row.get('type') == 'user':          # 사용자 메시지·도구 결과 → 그 앞은 작업 중
            break
        if row.get('type') != 'assistant':
            continue
        content = row.get('message', {}).get('content') or []
        if any(isinstance(c, dict) and c.get('type') == 'tool_use' for c in content):
            # 같은 줄에 도구 호출과 글이 같이 있으면 도구 호출 뒤 글만
            tail = []
            for c in reversed(content):
                if isinstance(c, dict) and c.get('type') == 'tool_use':
                    break
                if isinstance(c, dict) and c.get('type') == 'text':
                    tail.append(c.get('text', ''))
            texts.extend(tail)
            break
        for c in reversed(content):
            if isinstance(c, dict) and c.get('type') == 'text':
                texts.append(c.get('text', ''))
    return '\n'.join(reversed(texts))


HANGUL = re.compile(r'[가-힣ㄱ-ㆎ]')
LATIN = re.compile(r'[A-Za-z]')
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]+")
FUNC = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'and', 'or', 'but', 'to', 'of', 'for', 'with', 'on',
        'in', 'at', 'by', 'from', 'it', 'its', "it's", 'this', 'that', 'these', 'those', 'i', "i'll", "i'm", 'you', 'your',
        'we', 'they', 'will', 'would', 'can', 'could', 'should', 'has', 'have', 'had', 'do', 'does', 'did', 'not', 'no',
        'now', 'still', 'so', 'as', 'if', 'then', 'there', 'here', 'what', 'which', 'when', 'because', 'all', 'both'}


def _func(words: list[str]) -> int:
    return sum(w.lower() in FUNC for w in words)


def _clean(text: str) -> str:
    text = re.sub(r'```.*?```', '', text, flags=re.S)          # 코드 블록
    text = re.sub(r'`[^`]*`', '', text)                         # 인라인 코드(명령·경로·이름)
    text = re.sub(r'\[[^\]\n]*\]\([^)\n]*\)', '', text)          # 마크다운 링크 통째(출처 제목은 남의 글)
    text = re.sub(r'https?://\S+', '', text)                    # 주소
    text = re.sub(r'(?<!\w)[\w.\-]*[/\\][\w./\\\-가-힣]+', '', text)  # 파일 경로
    return text


def english_lines(text: str) -> list[str]:
    out = []
    for line in _clean(text).splitlines():
        if HANGUL.search(line):
            continue
        words = WORD.findall(line)
        if len(words) >= 5 and _func(words) >= 2:
            out.append(line.strip()[:80])
    return out


def mostly_english(text: str) -> bool:
    t = _clean(text)
    h, l = len(HANGUL.findall(t)), len(LATIN.findall(t))
    return l >= 40 and l > h and _func(WORD.findall(t)) >= 8


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
        '마지막 답이 영어입니다 — 프로젝트 훅 .claude/hooks/korean_guard.py (사용자 지시 11-28: 결과를 알려 줄 때는 한국어).\n'
        '사용자에게 결과를 알리는 마지막 답을 한국어로 다시 쓰세요(작업 중 글은 영어여도 됨, 명령·경로·코드 이름은 `백틱` 안에 두면 됩니다).'
        + sample,
        file=sys.stderr,
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
