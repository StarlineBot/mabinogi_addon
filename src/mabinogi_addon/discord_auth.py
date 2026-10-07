"""Discord 로그인 (OAuth2 Implicit Grant).

애드온 사용자가 Discord로 로그인해 자신의 user_id를 앱에 넘긴다 → 문의 글에 그
user_id가 실려, 제작자가 디스코드에서 답하면 봇이 그 사용자에게 DM으로 전달한다.

Implicit grant(response_type=token)를 쓰므로 **client secret이 필요 없다**(배포 앱에
비밀을 넣지 않는다). 토큰은 리다이렉트 URL의 fragment(#...)로 와서 서버가 직접 못
읽으므로, 콜백 페이지의 작은 JS가 fragment를 질의문자열로 바꿔 로컬 서버에 되돌린다.

로그인 흐름 전체가 사용자 PC(localhost)에서 일어난다. 네트워크 호출(사용자 조회)이
있으므로 UI 스레드가 아니라 백그라운드 스레드에서 login()을 호출한다.
"""

from __future__ import annotations

import http.server
import json
import logging
import secrets
import socketserver
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

_log = logging.getLogger("mabinogi_addon.discord")

# 공개값(비밀 아님). 포털 OAuth2 → Redirects에 REDIRECT_URI를 '똑같이' 등록해야 한다.
CLIENT_ID = "1172437289339727913"
PORT = 53123
REDIRECT_URI = f"http://localhost:{PORT}/callback"

AUTH_BASE = "https://discord.com/api/oauth2/authorize"
USER_URL = "https://discord.com/api/users/@me"

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
  <p>디스코드 계정이 연결되었습니다.<br>
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
          '디스코드 계정이 연결되었습니다.<br>이 창을 닫고 앱으로 돌아가세요.';
      }, 300);
    }
  }, 1000);
</script>
"""


def authorize_url(state: str) -> str:
    """Discord 인증 페이지 URL(implicit: 토큰을 fragment로 돌려줌)."""
    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "token",
            "scope": "identify",
            "state": state,
        }
    )
    return f"{AUTH_BASE}?{query}"


def fetch_user(
    access_token: str, *, urlopen=urllib.request.urlopen, timeout: float = 5.0
) -> tuple[str, str]:
    """액세스 토큰으로 내 (user_id, 표시이름) 조회."""
    req = urllib.request.Request(
        USER_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            # Discord API는 User-Agent를 요구(없으면 Cloudflare 403).
            "User-Agent": (
                "mabinogi-addon "
                "(https://github.com/StarlineBot/mabinogi_addon, 1.0)"
            ),
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    uid = str(data.get("id", ""))
    name = data.get("global_name") or data.get("username") or uid
    return uid, name


class _ReuseTCPServer(socketserver.ThreadingTCPServer):
    # ThreadingTCPServer: 요청마다 스레드로 처리 → serve_forever가 select 루프에 머물러
    # shutdown()이 교착되지 않는다(단일 스레드 TCPServer는 연결이 물리면 shutdown이 멈춤).
    allow_reuse_address = True  # 재시도 시 포트 '사용 중' 방지
    daemon_threads = True  # 남은 요청 스레드가 종료를 막지 않게


def login(*, open_browser=webbrowser.open, timeout: float = 120.0):
    """브라우저로 Discord 로그인 → (user_id, 이름). 실패/취소 시 None.

    로컬 루프백 서버를 잠깐 띄워 콜백을 받고, 사용자 조회까지 마친 뒤 닫는다.
    """
    state = secrets.token_urlsafe(16)
    captured: dict[str, str | None] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # 서버 로그 끔
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                # fragment(#access_token=...)는 서버가 못 보므로 JS로 질의문자열화해 재요청.
                self._send(
                    "<script>location.replace('/token?'"
                    "+location.hash.substring(1))</script>"
                )
            elif parsed.path == "/token":
                params = urllib.parse.parse_qs(parsed.query)
                captured["access_token"] = (params.get("access_token") or [None])[0]
                captured["state"] = (params.get("state") or [None])[0]
                _log.info(
                    "콜백 수신: token=%s state=%s",
                    "있음" if captured["access_token"] else "없음",
                    "있음" if captured["state"] else "없음",
                )
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

    try:
        server = _ReuseTCPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        _log.warning("로컬 서버 바인드 실패(포트 %d): %s", PORT, exc)
        return None
    server.timeout = 1.0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _log.info("로그인 시작: 브라우저 열기")
        open_browser(authorize_url(state))
        if not done.wait(timeout):
            _log.warning("로그인 시간 초과(%.0fs) — 승인 안 됨", timeout)
            return None  # 시간 초과(사용자가 승인 안 함)
        token = captured.get("access_token")
        if not token:
            _log.warning("콜백에 access_token 없음")
            return None
        if captured.get("state") != state:
            _log.warning("state 불일치 — 변조 의심(무시)")
            return None
        try:
            uid, name = fetch_user(token)
        except urllib.error.HTTPError as exc:
            _log.warning("사용자 조회 실패(HTTP %s): %s", exc.code, exc.reason)
            return None
        except Exception as exc:  # noqa: BLE001 — 네트워크/파싱 오류
            _log.warning("사용자 조회 실패: %r", exc)
            return None
        _log.info("로그인 성공: %s (%s)", name, uid)
        return uid, name
    finally:
        # 정리는 데몬 스레드로 — shutdown()이 혹시 늦어져도 login() 반환(=결과 전달)을
        # 막지 않는다. 이게 막히면 UI가 로그인 결과를 못 받아 저장·표시가 안 된다.
        def _cleanup() -> None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as exc:  # noqa: BLE001 — 정리 실패는 무시
                _log.warning("로컬 서버 종료 실패: %r", exc)
            else:
                _log.info("로컬 서버 종료")

        threading.Thread(target=_cleanup, daemon=True).start()
