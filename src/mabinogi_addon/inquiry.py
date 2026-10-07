"""문의 전송 (Discord 웹훅).

설정의 '문의하기'에서 입력한 제목·내용을 제작자 Discord 채널로 보낸다.
표준 라이브러리 urllib만 사용(의존성 추가 없음). 네트워크 호출이므로 UI 스레드에서
직접 부르지 말고 데몬 스레드에서 호출한다(응답은 Qt 시그널로 UI에 돌려준다).
"""

from __future__ import annotations

import json
import urllib.request

# Discord 임베드 제한: 제목 256자, 설명 4096자
_TITLE_MAX = 256
_DESC_MAX = 4000
_EMBED_COLOR = 0x00B894  # 앱 포인트 색

# Discord 웹훅 성공 응답
_OK_STATUS = (200, 204)


def send_inquiry(
    webhook_url: str,
    title: str,
    content: str,
    *,
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

    embed = {
        "title": title[:_TITLE_MAX],
        "description": content[:_DESC_MAX],
        "color": _EMBED_COLOR,
    }
    data = json.dumps({"embeds": [embed]}).encode("utf-8")
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
