"""Claude Code Stop 훅 — 확인하지 않고 '모른다·확인 못 했다'로 끝내는 답을 막는다(사용자 지시 11-17).

말로 한 약속은 세션이 압축되면 사라지므로 장치로 둔다. 마지막 사용자 메시지 뒤 에이전트가 쓴 글에
금지 표현이 있으면 응답 종료를 막고, 직접 확인한 뒤 '된다' 또는 '안 된다(이유)'로 다시 답하게 한다.
같은 종료 시도에서 한 번만 막는다(stop_hook_active) — 정말 확인이 불가능한 경우가 무한 반복되지 않게.

원인 단정 금지(사용자 지시 11-27 — 제보를 그림·인식 문제로 바꿔 읽고 재현 없이 '원인을 찾았다'고 답한 일):
답에 '원인'을 쓰면 같은 답에 '재현:' 줄(실제로 돌린 명령·결과, 또는 '재현: 안 됨 — 다음에 볼 곳')이 있어야 한다.
이 규칙은 stop_hook_active여도 막는다 — '재현:' 줄을 쓰면 언제든 풀리므로 무한 반복되지 않는다.
사용자 탓 금지(사용자 지시 11-28 — 웃음 대기로 잘못 들어간 말하기 영상을 QA가 보지 않고 통과시킨 뒤
'다른 동작을 보신 것', '클릭하셨나요'처럼 사용자가 잘못 본 것으로 몰아간 일. 세션이 압축되면 말로 한 반성은 사라지므로 장치로 둔다):
사용자가 잘못 봤다·착각했다는 말, 사용자가 한 조작·조건을 되묻는 말이 따옴표·인용 밖에 있으면 막는다.
stop_hook_active여도 막는다 — 그 말을 빼고 다시 쓰면 풀린다.
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


CAUSE = re.compile(r'원인')
REPRO_LINE = re.compile(r'(?m)^[ \t>*\-]*(?:\*\*)?재현(?:\*\*)?\s*[:：]')


def _strip_quotes(text: str) -> str:
    """코드·인용 블록·따옴표 안 글자 빼기 — 명령·남의 말·규칙 설명은 결론이 아님."""
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'(?m)^\s*>.*$', '', text)
    return re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|\'[^\'\n]*\'', '', text)


def unproven_cause(text: str) -> bool:
    """'원인'을 말하는데 '재현:' 줄이 없음(사용자 지시 11-27)."""
    return bool(CAUSE.search(_strip_quotes(text))) and not REPRO_LINE.search(text)


BLAME = re.compile(
    r'잘못\s*(?:보|들|이해하|아)(?:신|셨|시)|착각|오인하|헷갈리(?:신|셨)'
    r'|다른\s*(?:동작|장면|화면|캐릭터|창)을?\s*(?:보|들)(?:신|셨)'
    r'|(?:클릭|조작|소리|게임|설정|마우스|알림)[^.?!\n]{0,24}(?:하셨|켜셨|누르셨|움직이셨|켜져\s*있었|켜\s*두셨)[^.?!\n]{0,8}\?'
)


def blames_user(text: str) -> list[str]:
    """사용자가 잘못 봤다고 하거나 사용자 조작을 되묻는 말(사용자 지시 11-28)."""
    text = _strip_quotes(text)
    # 자기 잘못을 적은 말('잘못 보셨다고 몰아간 것')은 사용자 탓이 아님
    return sorted({m.group(0) for m in BLAME.finditer(text)
                   if not re.match(r'[^.?!\n]{0,8}(?:몰아|탓|말한|한\s*것|처럼\s*말)', text[m.end():])})


def violations(text: str) -> list[str]:
    # 코드 블록·인라인 코드 안 글자는 제외(명령·인용 예시)
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'`[^`]*`', '', text)
    # 인용 블록(> 로 시작하는 줄 — 번역·남의 말 옮김)은 제외
    text = re.sub(r'(?m)^\s*>.*$', '', text)
    # 따옴표로 인용한 표현(규칙 설명 등)은 제외 — 실제 결론이 아님
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|\'[^\'\n]*\'', '', text)
    return sorted({m.group(0) for m in BANNED.finditer(text)})


def main() -> int:
    try:
        data = json.load(sys.stdin)
        reply = last_reply(Path(data['transcript_path']))
        cause = unproven_cause(reply)
        blame = blames_user(reply)
        found = [] if data.get('stop_hook_active') else violations(reply)
    except Exception:
        return 0
    if blame:
        print(
            f"답에 '{', '.join(blame)}' 표현이 있습니다 — 프로젝트 훅 .claude/hooks/answer_guard.py (사용자 지시 11-28).\n"
            '사용자가 본 것·한 조작은 사실입니다. 잘못 봤다고 하거나 조작 여부를 되묻지 말고, '
            '그 말 그대로의 증상을 앱·자료에서 찾아 재현한 결과로 다시 답하세요.',
            file=sys.stderr,
        )
        return 2
    if cause:
        print(
            "답에 '원인'이 있는데 '재현:' 줄이 없습니다 — 프로젝트 훅 .claude/hooks/answer_guard.py (사용자 지시 11-27).\n"
            '사용자 제보는 문장 그대로 증상으로 받고(그림·인식 문제로 바꿔 읽지 않음), 앱을 돌려 재현한 뒤에만 원인을 말하세요. '
            "답에 '재현: <돌린 명령과 결과>' 줄을 넣거나, 재현이 안 됐으면 '재현: 안 됨 — <다음에 볼 곳>'으로 쓰고 원인은 단정하지 마세요.",
            file=sys.stderr,
        )
        return 2
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
