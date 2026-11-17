"""Claude Code Stop 훅 — 확인하지 않고 '모른다·확인 못 했다'로 끝내는 답을 막는다(사용자 지시 11-17).

말로 한 약속은 세션이 압축되면 사라지므로 장치로 둔다. 마지막 사용자 메시지 뒤 에이전트가 쓴 글에
금지 표현이 있으면 응답 종료를 막고, 직접 확인한 뒤 '된다' 또는 '안 된다(이유)'로 다시 답하게 한다.
같은 종료 시도에서 한 번만 막는다(stop_hook_active) — 정말 확인이 불가능한 경우가 무한 반복되지 않게.
훅이 실패하면 막지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BANNED = re.compile(
    r'확인\s*(?:못|하지\s*못|을\s*못|이\s*안\s*됐|할\s*수\s*없)'
    r'|모르겠|모릅니다|알\s*수\s*없|해\s*봐야\s*(?:알|압니다)|장담\s*(?:못|할\s*수\s*없)'
    r'|아직\s*(?:모름|확인\s*전)'
)


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


def violations(text: str) -> list[str]:
    # 코드 블록·인라인 코드 안 글자는 제외(명령·인용 예시)
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'`[^`]*`', '', text)
    # 따옴표로 인용한 표현(규칙 설명 등)은 제외 — 실제 결론이 아님
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|\'[^\'\n]*\'', '', text)
    return sorted({m.group(0) for m in BANNED.finditer(text)})


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if data.get('stop_hook_active'):
            return 0
        found = violations(last_reply(Path(data['transcript_path'])))
    except Exception:
        return 0
    if not found:
        return 0
    print(
        f"답에 '{', '.join(found)}' 표현이 있습니다 — 프로젝트 훅 .claude/hooks/answer_guard.py (CLAUDE.md 소통 첫 줄).\n"
        '확인할 수 있는 건 지금 직접 확인하세요(비용 없는 시험: 잘못된 입력으로 권한 확인, 조회 API, 로컬 재현 등). '
        "그 결과로 '된다' 또는 '안 된다(이유)'로 다시 답하세요. 정말 이 환경에서 볼 수 없는 것이면 "
        "'안 된다: <무엇이 없어서>'와 사용자가 줄 자료를 한 줄로 적으세요.",
        file=sys.stderr,
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
