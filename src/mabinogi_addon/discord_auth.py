"""디스코드 로그인 — 서버 경유(계정 관리 명세 3.2, 0.46.0부터).

1. 앱이 `localhost:53123`에서 잠깐 기다리고, 브라우저로 서버 `/auth/start?state=…&port=53123`을 연다.
2. 서버가 디스코드 인증(Authorization Code — client secret은 서버에만)·코드 교환·사용자 확인 뒤 **서명한 앱 토큰**을 만든다.
3. 서버가 브라우저를 `http://localhost:53123/callback?token=…&state=…`로 보낸다 → 앱이 state를 확인하고
   내장 공개 키로 토큰 서명을 확인(account.verify_token)한 뒤 돌려준다(저장은 화면 쪽).

예전(0.45.x까지)은 디스코드 Implicit Grant로 앱이 사용자 정보를 직접 받아 config에 적었다 — 서명이 없어 파일을 고치면
로그인·제작자 흉내가 됐다. 로그인 흐름은 사용자 PC(localhost)와 서버만 오가고, 네트워크를 기다리므로 작업 스레드에서 부른다.
"""

from __future__ import annotations

import http.server
import logging
import secrets
import socketserver
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import account

_log = logging.getLogger("mabinogi_addon.discord")

PORT = account.PORT

# 마지막 로그인 실패 이유(화면 문구) — 서버 콜백 error= 값 그대로 + timeout
ERROR_TEXT = {"access_denied": "로그인을 취소했어요.", "login_failed": "로그인하지 못했어요 — 다시 시도해 주세요.",
              "blocked": "이 계정은 지금 로그인할 수 없어요.", "timeout": "로그인 시간이 지났어요 — 다시 시도해 주세요."}
last_error = ["timeout"]

# 로그인 성공 시 브라우저에 보여줄 페이지(라이트/다크 모두 대응하는 카드).
_SUCCESS_BODY = """
<title>로그인 완료</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center;
    justify-content:center; padding:24px;
    background:#1e1f24; color:#eef0f4;
    font-family:'Malgun Gothic','Apple SD Gothic Neo',system-ui,sans-serif; }
  .card { width:100%; max-width:360px; background:#26272e;
    border:1px solid #33343c; border-radius:16px; padding:40px 36px;
    text-align:center; box-shadow:0 10px 34px rgba(0,0,0,.4); }
  .check { width:66px; height:66px; border-radius:50%; background:#00B894;
    display:flex; align-items:center; justify-content:center;
    margin:0 auto 22px; font-size:36px; line-height:1; color:#fff; }
  h1 { margin:0 0 10px; font-size:22px; font-weight:700; }
  p { margin:0; color:#a7acb6; font-size:15px; line-height:1.55; }
  .app { margin-top:24px; font-size:13px; color:#6f7580; }
</style>
<div class="card">
  <div class="check">&#10003;</div>
  <h1>로그인 완료</h1>
  <p>디스코드 계정이 연결되었어요.<br>
     이 창은 <b id="sec">5</b>초 후 자동으로 닫힙니다.</p>
  <div class="app">섯다라인 마비노기 애드온</div>
</div>
<script>
  var n = 5;
  var el = document.getElementById('sec');
  var t = setInterval(function () {
    n -= 1;
    if (el) el.textContent = n;
    if (n <= 0) {
      clearInterval(t);
      window.close();               // 스크립트로 연 창이 아니면 막힐 수 있음
      // 닫기가 막히면 안내 문구로 교체
      setTimeout(function () {
        document.querySelector('p').innerHTML =
          '디스코드 계정이 연결되었어요.<br>이 창을 닫고 앱으로 돌아가세요.';
      }, 300);
    }
  }, 1000);
</script>
"""


class _ReuseTCPServer(socketserver.ThreadingTCPServer):
    # ThreadingTCPServer: 요청마다 스레드로 처리 → serve_forever가 select 루프에 머물러
    # shutdown()이 교착되지 않는다(단일 스레드 TCPServer는 연결이 물리면 shutdown이 멈춤).
    allow_reuse_address = True  # 재시도 시 포트 '사용 중' 방지
    daemon_threads = True  # 남은 요청 스레드가 종료를 막지 않게


def login(*, open_browser=webbrowser.open, timeout: float = 120.0, base: str | None = None,
          public_key_hex: str | None = None) -> str | None:
    """브라우저로 서버 경유 디스코드 로그인 → 서명 확인된 토큰 문자열. 실패·취소·state 불일치·서명 틀림이면 None."""
    state = secrets.token_urlsafe(16)  # 22자 [A-Za-z0-9_-] — 서버 규격 8~128자
    last_error[0] = "timeout"
    captured: dict[str, str | None] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # 서버 로그 끔
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                params = urllib.parse.parse_qs(parsed.query)
                captured["token"] = (params.get("token") or [None])[0]
                captured["state"] = (params.get("state") or [None])[0]
                captured["error"] = (params.get("error") or [None])[0]  # access_denied·login_failed·blocked
                _log.info("콜백 수신: token=%s state=%s", "있음" if captured["token"] else "없음",
                          "있음" if captured["state"] else "없음")
                self._send(_SUCCESS_BODY)
                done.set()
            else:
                self.send_response(404)
                self.end_headers()

        def _send(self, body: str):
            data = f"<!doctype html><meta charset=utf-8>{body}".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = None
    for attempt in range(20):  # 바로 전 로그인의 로컬 서버가 닫히는 중이면 잠깐 기다렸다 다시(최대 약 2초)
        try:
            server = _ReuseTCPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError as exc:
            if attempt == 19:
                _log.warning("로컬 서버 바인드 실패(포트 %d): %s", PORT, exc)
                last_error[0] = "login_failed"
                return None
            import time
            time.sleep(0.1)
    server.timeout = 1.0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _log.info("로그인 시작: 브라우저 열기(서버 경유)")
        open_browser(account.start_url(state, base=base or account.SERVER_URL))
        if not done.wait(timeout):
            _log.warning("로그인 시간 초과(%.0fs) — 승인 안 됨", timeout)
            return None
        token = captured.get("token")
        if captured.get("state") != state:
            _log.warning("state 불일치 — 변조 의심(무시)")
            last_error[0] = "login_failed"
            return None
        if captured.get("error"):
            _log.info("서버 로그인 결과: %s", captured["error"])
            last_error[0] = captured["error"] if captured["error"] in ERROR_TEXT else "login_failed"
            return None
        if not token or account.verify_token(token, public_key_hex=public_key_hex) is None:
            _log.warning("토큰 없음·서명 확인 실패 — 로그인 안 함")
            last_error[0] = "login_failed"
            return None
        _log.info("로그인 성공(토큰 서명 확인)")
        return token
    finally:
        # 정리는 데몬 스레드로 — shutdown()이 늦어져도 login() 반환(=결과 전달)을 막지 않는다.
        def _cleanup() -> None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as exc:  # noqa: BLE001 — 정리 실패는 무시
                _log.warning("로컬 서버 종료 실패: %r", exc)
            else:
                _log.info("로컬 서버 종료")

        threading.Thread(target=_cleanup, daemon=True).start()
