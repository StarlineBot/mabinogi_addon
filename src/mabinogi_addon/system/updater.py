"""자동 업데이트 (기획: 공개 저장소의 version.json 확인 → exe 전면 교체).

배포본(onefile exe)은 통째로 교체한다(델타 아님). 실행 중인 exe는 Windows에서
'삭제/덮어쓰기'는 막혀도 '이름 변경(rename)'은 허용되므로, 아래 **B안(이름 트릭)**을
쓴다:

1. 현재 exe 를 ``<exe>.old`` 로 rename (실행 중이어도 가능)
2. 내려받은 새 exe 를 원래 이름으로 옮김
3. 새 exe 재실행 후 현재 프로세스 종료
4. 다음 실행 때 ``.old`` 정리(cleanup_old)

- 확인 주소: 공개 저장소 main 의 version.json (raw).
- 공개 호스팅이라 앱에 토큰이 필요 없다(다운로드도 공개 URL).
- 개발(uv, __version__=="0.0.0")에선 동작하지 않는다(can_update=False).

Windows 전용 동작이지만, 네트워크 확인(check_latest)은 OS 무관하게 돈다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from .. import paths
from ..version import __version__

_log = logging.getLogger("mabinogi_addon.updater")

# 공개 저장소 main 의 version.json (저장소를 바꾸면 여기만 고치면 된다).
VERSION_URL = (
    "https://raw.githubusercontent.com/"
    "StarlineBot/mabinogi_addon-releases/main/version.json"
)
_UA = {"User-Agent": "mabinogi-addon-updater"}

_ssl_ctx = None


def _ssl_context():
    """certifi의 CA 번들로 SSL 컨텍스트를 만든다(한 번 만들어 재사용).

    왜: 일부 PC는 Windows 신뢰 저장소에 깃허브 인증서의 발급자(중간 CA)가 없어
    기본 검증이 CERTIFICATE_VERIFY_FAILED로 터진다(업데이트 다운로드 실패). 앱이
    함께 담은 certifi 번들을 쓰면 머신 저장소 상태와 무관하게 검증된다. certifi가
    없으면 None(기본 컨텍스트)으로 폴백한다.
    """
    global _ssl_ctx
    if _ssl_ctx is None:
        try:
            import ssl

            import certifi

            _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001 — certifi 없거나 실패 시 기본 컨텍스트
            _ssl_ctx = False  # None과 구분(재시도 안 하게): urlopen엔 None으로 넘김
    return _ssl_ctx or None


def can_update() -> bool:
    """배포본(exe)이고 버전이 실제 릴리스 버전일 때만 업데이트를 시도한다."""
    return paths.is_frozen() and __version__ != "0.0.0"


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_newer(latest: str, current: str) -> bool:
    return _parse(latest) > _parse(current)


def check_latest() -> dict | None:
    """version.json 을 읽어 현재보다 새 버전이면 그 정보(dict)를, 아니면 None.

    네트워크·파싱 오류는 전부 조용히 None(업데이트는 부가 기능이라 앱 실행을 막지 않음).
    """
    try:
        # 캐시 무효화: raw.githubusercontent는 CDN(Fastly)이 엣지별로 ~5분 캐시해,
        # 릴리스 직후엔 지역에 따라 옛 version.json이 돌아온다(실행 중/시작 시 감지 지연).
        # 매번 다른 쿼리(?t=epoch) + no-cache 헤더로 엣지 캐시를 건너뛰고 원본을 받는다.
        import time

        bust = f"{VERSION_URL}?t={int(time.time())}"
        headers = {**_UA, "Cache-Control": "no-cache", "Pragma": "no-cache"}
        req = urllib.request.Request(bust, headers=headers)
        with urllib.request.urlopen(req, timeout=10, context=_ssl_context()) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log.info("업데이트 확인 실패(무시): %r", exc)
        return None
    latest = str(data.get("version", "")).strip()
    if latest and is_newer(latest, __version__):
        _log.info("새 버전 발견: %s (현재 %s)", latest, __version__)
        return data
    return None


def cleanup_old() -> None:
    """교체 후 남은 ``<exe>.old`` 를 지운다(실행 시작 시 1회 호출)."""
    if not paths.is_frozen():
        return
    old = Path(sys.executable + ".old")
    try:
        if old.exists():
            old.unlink()
            _log.info("이전 버전 정리: %s", old.name)
    except OSError as exc:
        _log.info("이전 버전 정리 실패(무시): %r", exc)


def _enough_disk(need_bytes: int, where: Path) -> bool:
    try:
        free = shutil.disk_usage(where).free
    except OSError:
        return True  # 확인 실패 시엔 막지 않는다(다운로드 중 오류로 처리)
    return free > need_bytes


def download(info: dict, progress_cb=None) -> Path:
    """새 exe 를 ``<exe>.new`` 로 받고 sha256 검증 후 경로 반환.

    progress_cb(pct:int) 가 있으면 0~100 진행률 콜백. 실패 시 예외.
    """
    exe = Path(sys.executable)
    dest = Path(str(exe) + ".new")
    url = info["url"]
    want = str(info.get("sha256", "")).lower()
    size = int(info.get("size") or 0)

    # 교체는 현재 exe 옆에 새 파일을 만들었다가 rename 하므로, 같은 볼륨에 여유가
    # 필요하다. 새 exe(size) + 잠깐 .old 가 공존하므로 넉넉히 2배로 본다.
    if size and not _enough_disk(size * 2, exe.parent):
        raise OSError("디스크 여유 공간이 부족합니다(약 "
                      f"{size * 2 // (1024 * 1024)}MB 필요).")

    sha = hashlib.sha256()
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(
            req, timeout=30, context=_ssl_context()
        ) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or size or 0)
            got = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                got += len(chunk)
                if total and progress_cb:
                    progress_cb(min(100, int(got * 100 / total)))
    except Exception:
        _safe_unlink(dest)
        raise

    if want and sha.hexdigest().lower() != want:
        _safe_unlink(dest)
        raise ValueError("내려받은 파일 검증(sha256) 실패 — 다시 시도해 주세요.")
    return dest


def apply_update(new_path: Path) -> None:
    """B안(이름 트릭)으로 교체하고 새 exe 를 재실행한다. 호출 측은 곧 앱을 종료.

    이 함수가 성공해 돌아오면 디스크의 exe 는 이미 새 버전이고, 새 프로세스가 떠 있다.
    """
    import subprocess

    exe = Path(sys.executable)
    old = Path(str(exe) + ".old")

    _safe_unlink(old)  # 이전 .old 잔재 제거(있어도 rename이 덮지만 안전하게)
    os.replace(exe, old)  # 실행 중 exe 를 .old 로 rename (Windows 허용)
    try:
        os.replace(new_path, exe)  # 새 exe 를 원래 이름으로
    except OSError:
        os.replace(old, exe)  # 롤백: 원래 exe 복구
        raise

    # 새 exe 실행(현재 프로세스는 이미 관리자 → 새 exe도 UAC 창 없이 승격 유지).
    creationflags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS
    subprocess.Popen(  # 고정 경로(자기 자신), 사용자 입력 없음
        [str(exe)],
        close_fds=True,
        creationflags=creationflags,
        env=_relaunch_env(),
    )


def _relaunch_env() -> dict[str, str]:
    """자식(새 exe)이 '부모의 _MEI 추출 폴더'를 재사용하지 않도록 PyInstaller 내부
    환경변수를 제거한 환경을 만든다.

    onefile 부트로더는 _MEIPASS2(구버전)·_PYI_*(신버전) 환경변수로 '이미 풀었음(=재실행
    자식)'을 판단한다. 업데이트가 새 exe를 Popen으로 띄울 때 이 값이 그대로 상속되면,
    새 프로세스가 자기 에셋을 새로 풀지 않고 '종료 예정인 옛 프로세스의 _MEI'를 가리킨다.
    옛 프로세스가 그 폴더를 지우면 → 번들 아이콘·템플릿이 사라지고('아이콘 없어짐'),
    'Failed to remove temporary directory' 경고가 뜬다. 그래서 상속을 끊는다.
    """
    env = os.environ.copy()
    for key in list(env):
        if key == "_MEIPASS2" or key.startswith("_PYI"):
            env.pop(key, None)
    return env


def _safe_unlink(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
