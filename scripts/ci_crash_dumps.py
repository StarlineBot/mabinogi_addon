"""Windows CI 시작 스모크 크래시 덤프 수집(2026-10-25 사용자 승인).

test_startup_smoke[True]의 window.close()에서 access violation(CI #133·#134·#135, 실기 미재현). 파이썬 스택은 테스트 39행뿐이라
네이티브 스택(Qt 모듈·함수)이 필요하다.

    python -m scripts.ci_crash_dumps arm <폴더>     # 스모크 전: WER LocalDumps(python.exe, 전체 덤프) 설정 + 환경 기록
    python -m scripts.ci_crash_dumps report <폴더>  # 실패 뒤: 덤프마다 cdb로 예외 스택을 뽑아 로그에(앱 모듈·Qt 프레임 요약)

읽기·진단만 한다. 테스트 결과를 바꾸지 않는다(스모크 실패는 그대로 잡 실패).
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path

KEY = r'SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\python.exe'
DUMP_TYPE_FULL = 2
CDB_CANDIDATES = (r'C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe',
                  r'C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe')
# 예외 문맥(.ecxr) 스택, 전체 스레드 스택, 자동 분석, 적재 모듈(버전 비교용)
CDB_COMMANDS = '.symfix+ {cache}; .reload; .ecxr; kn 60; ~*kn 30; !analyze -v; lmv m Qt6*; lmv m python3*; q'
FRAME = re.compile(r'^\s*(?:[0-9a-f]{2}\s+)?[0-9a-f`]+\s+[0-9a-f`]+\s+(?P<module>[\w.]+)!(?P<symbol>\S+)', re.I)


def environment() -> list[str]:
    """덤프 해석에 필요한 실행 환경(러너 간 비교용). 비밀값·경로 외 정보 없음."""
    lines = [f'python {sys.version.split()[0]} ({platform.python_implementation()}) {sys.executable}',
             f'os {platform.platform()}']
    try:
        import PySide6
        import shiboken6
        from PySide6 import QtCore
        lines.append(f'PySide6 {PySide6.__version__} · shiboken6 {shiboken6.__version__} · Qt {QtCore.qVersion()}')
    except Exception as exc:  # 진단만
        lines.append(f'PySide6 확인 실패: {type(exc).__name__}')
    return lines


def arm(folder: Path) -> int:
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for line in environment():
        print('[crash-dumps]', line)
    if sys.platform != 'win32':
        print('[crash-dumps] Windows가 아니라 설정하지 않아요.')
        return 0
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
        winreg.SetValueEx(key, 'DumpFolder', 0, winreg.REG_EXPAND_SZ, str(folder))
        winreg.SetValueEx(key, 'DumpType', 0, winreg.REG_DWORD, DUMP_TYPE_FULL)
        winreg.SetValueEx(key, 'DumpCount', 0, winreg.REG_DWORD, 5)
    print(f'[crash-dumps] WER LocalDumps 설정: python.exe → {folder} (전체 덤프)')
    return 0


def summarize(text: str) -> list[str]:
    """cdb 출력에서 프레임(모듈!함수)만 순서대로 뽑아 앞쪽과 Qt·PySide·앱 모듈 프레임을 요약한다."""
    frames = []
    for line in text.splitlines():
        match = FRAME.match(line)
        if match:
            frames.append(f"{match['module']}!{match['symbol']}")
    interesting = [f for f in frames if re.match(r'(Qt6|qwindows|pyside6|shiboken6|python3)', f, re.I)]
    return frames[:25] + (['— Qt·PySide·python 프레임 —'] + list(dict.fromkeys(interesting))[:40] if interesting else [])


def cdb() -> str | None:
    for path in CDB_CANDIDATES:
        if Path(path).is_file():
            return path
    return None


def report(folder: Path) -> int:
    dumps = sorted(folder.glob('*.dmp')) if folder.exists() else []
    if not dumps:
        print(f'[crash-dumps] 덤프 없음({folder}). WER가 만들지 않았거나 크래시가 python.exe 밖에서 났어요.')
        return 0
    debugger = cdb()
    for dump in dumps[:3]:
        print(f'[crash-dumps] {dump.name} {dump.stat().st_size / 1024 / 1024:.0f}MB')
        if debugger is None:
            print('[crash-dumps] cdb 없음 — 덤프 파일(결과물)을 내려받아 확인해 주세요.')
            continue
        cache = folder / 'symbols'
        command = [debugger, '-z', str(dump), '-y', str(Path(sys.base_prefix)), '-c', CDB_COMMANDS.format(cache=cache)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=240)
            output = result.stdout
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
            print('[crash-dumps] cdb 시간 초과(240초) — 받은 만큼만 보여줘요.')
        (folder / (dump.stem + '.cdb.txt')).write_text(output, encoding='utf-8')
        print('[crash-dumps] 예외 스택 요약:')
        for line in summarize(output):
            print('   ', line)
        for marker in ('EXCEPTION_RECORD', 'ExceptionCode', 'FAULTING_IP', 'SYMBOL_NAME', 'MODULE_NAME', 'IMAGE_NAME',
                       'FAILURE_BUCKET_ID'):
            for line in output.splitlines():
                if line.strip().startswith(marker):
                    print('   ', line.strip())
                    break
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ('arm', 'report'):
        print(__doc__)
        return 2
    folder = Path(os.path.expandvars(argv[1]))
    return arm(folder) if argv[0] == 'arm' else report(folder)


if __name__ == '__main__':
    sys.exit(main())
