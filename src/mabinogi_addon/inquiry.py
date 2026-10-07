"""문의 전송 (Discord 웹훅).

설정의 '문의하기'에서 입력한 제목·내용을 제작자 Discord 채널로 보낸다.
표준 라이브러리 urllib만 사용(의존성 추가 없음). 네트워크 호출이므로 UI 스레드에서
직접 부르지 말고 데몬 스레드에서 호출한다(응답은 Qt 시그널로 UI에 돌려준다).

포럼 채널 웹훅이면 thread_name으로 '문의 1건 = 포럼 글 1개'를 만든다(섯다라인봇
모드메일의 forum.threads.create와 같은 결과). 일반 텍스트 채널 웹훅이면 Discord가
thread_name을 거부(400)하므로 제목을 본문 맨 위에 붙여 일반 메시지로 재전송한다.

봇 토큰은 쓰지 않는다 — 배포 앱에 봇 토큰을 넣는 건 위험하고, 웹훅 URL은 채널
하나로 범위가 한정된 비밀이라 번들 대상으로 적절하다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_TITLE_MAX = 90  # 포럼 포스트 제목 길이(모드메일과 동일 기준)
_CONTENT_MAX = 1900  # Discord 메시지 content 한도(2000) 여유분

# Discord 웹훅 성공 응답(메시지=200/204, ?wait=true면 200)
_OK_STATUS = (200, 204)


def send_inquiry(
    webhook_url: str,
    title: str,
    content: str,
    *,
    username: str | None = None,
    timeout: float = 5.0,
    urlopen=urllib.request.urlopen,
) -> None:
    """Discord 웹훅으로 문의를 전송. 실패하면 예외를 던진다.

    urlopen은 테스트에서 가짜로 주입할 수 있다.
    """
    title = title.strip()
    content = content.strip()
    if not title or not content:
        raise ValueError("제목과 내용을 모두 입력하세요")
    if not webhook_url:
        raise ValueError("문의 채널(웹훅)이 설정되지 않았습니다")

    title = title[:_TITLE_MAX]
    body = content[:_CONTENT_MAX]
    payload: dict = {"content": body, "thread_name": title}
    if username:
        payload["username"] = username[:80]

    try:
        _post(webhook_url, payload, timeout, urlopen)
    except urllib.error.HTTPError as exc:
        # 포럼이 아닌 일반 채널 웹훅: thread_name 미지원 → 제목을 본문에 넣어 재전송.
        if exc.code == 400 and "thread_name" in payload:
            del payload["thread_name"]
            payload["content"] = f"**{title}**\n{body}"[:_CONTENT_MAX]
            _post(webhook_url, payload, timeout, urlopen)
        else:
            raise


def _post(webhook_url: str, payload: dict, timeout: float, urlopen) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", None)
        if status is not None and status not in _OK_STATUS:
            raise RuntimeError(f"웹훅 응답 코드 {status}")
