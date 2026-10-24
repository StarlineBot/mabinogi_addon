"""게임 우선순위 읽기 불일치 조사(최적화 명세 13.7, 리서치 7.7). Windows에서 게임을 켠 채 실행한다. 읽기만 한다.

실행(앱과 같은 권한으로 — 앱은 관리자 실행):
    uv run python -m scripts.diag_game_priority            # 등록한 게임 실행 파일 이름으로 찾기
    uv run python -m scripts.diag_game_priority Client.exe # 이름 직접 지정
    uv run python -m scripts.diag_game_priority --watch 60 # 60분 동안 1초마다 감시, 값이 바뀐 순간만 출력
작업 관리자 '세부 정보'에서 같은 PID의 '기본 우선 순위' 열을 보면서, 이 출력과 같은 순간에 비교한다.

같은 PID를 여러 경로로 동시에 읽어 어느 경로가 작업 관리자와 다른지 본다:
  ① 앱 FPS 기록과 같은 경로(pywin32 GetPriorityClass, 조회 제한 권한 핸들)
  ② ctypes GetPriorityClass, 조회 제한 권한(0x1000)
  ③ ctypes GetPriorityClass, 일반 조회 권한(0x400)
  ④ 프로세스 목록(Toolhelp)의 기본 우선순위 숫자(핸들 없음): 4 낮음 · 6 보통 미만 · 8 보통 · 10 보통 초과 · 13 높음 · 24 실시간
  ⑤ PowerShell Get-Process의 PriorityClass(.NET 경로)
같은 이름의 프로세스가 여러 개면 모두 출력한다(앱이 다른 PID를 읽는지 확인). 앱이 게임으로 고르는 PID도 함께 표시한다.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def watch(minutes, exe):
    """우선순위가 언제 바뀌는지 잡는다(리서치 7.7: 측정 내내 '보통'이었는데 측정 뒤 작업 관리자는 '높음').
    1초마다 같은 이름의 모든 프로세스를 두 경로(API·목록)로 읽어, 값이 바뀌거나 PID가 생기고 사라질 때만 시각과 함께 출력한다."""
    import time
    from mabinogi_addon.system import process_priority as pp
    print(f'{minutes}분 동안 감시해요. 게임을 평소처럼 하면서 두세요(던전 입장·로딩·채널 이동 포함). Ctrl+C로 멈춰요.')
    import win32gui, win32process

    def foreground_pid():
        try:
            return win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1]
        except Exception:
            return None

    last, end = {}, time.monotonic() + minutes * 60
    try:
        while time.monotonic() < end:
            listed = pp.list_base_priorities()
            front = foreground_pid()
            now = {}
            for pid, (name, base) in listed.items():
                if name.lower() == Path(exe).name.lower():
                    api, error = pp.api_priority(pid)
                    # 게임 창이 앞에 있는지도 함께 본다(가설: 게임이 뒤로 가면 스스로 '보통'으로 낮춤)
                    now[pid] = (pp.name(api) if api else f'실패({error})', base, front == pid)
            for pid in sorted(set(now) | set(last)):
                if now.get(pid) != last.get(pid):
                    stamp = time.strftime('%H:%M:%S')
                    if pid not in now:
                        print(f'{stamp} PID {pid} 종료')
                    else:
                        api_text, base, focused = now[pid]
                        where = '게임 창 앞' if focused else f'게임 창 뒤(앞: {listed.get(front, ("?",))[0] if front else "?"})'
                        print(f'{stamp} PID {pid} · API {api_text} · 목록 {base}({pp.name(pp.CLASS_OF_BASE.get(base)) if base in pp.CLASS_OF_BASE else "?"}) · {where}')
            last = now
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    print('감시 끝. 위 출력 전체를 보내 주세요.')
    return 0


def main(argv):
    if sys.platform != 'win32':
        print('Windows에서 실행해 주세요.')
        return 2
    if len(argv) > 1 and argv[1] == '--watch':
        from mabinogi_addon import config
        minutes = float(argv[2]) if len(argv) > 2 else 60
        exe = argv[3] if len(argv) > 3 else (config.load_game_exe() or 'Client.exe')
        return watch(minutes, exe)
    from mabinogi_addon import config
    from mabinogi_addon.system import process_priority as pp
    exe = argv[1] if len(argv) > 1 else (config.load_game_exe() or 'Client.exe')
    listed = pp.list_base_priorities()
    pids = sorted(pid for pid, (name, _) in listed.items() if name.lower() == Path(exe).name.lower())
    print(f'대상 이름: {exe} · 같은 이름 프로세스 {len(pids)}개: {pids}')
    try:
        from mabinogi_addon.system.window_capture import registered_game_target
        target = registered_game_target(None)
        print(f'앱이 게임으로 고르는 PID(등록 게임 창 기준): {target[1] if target else "없음(게임 창 미등록·미발견)"}')
    except Exception as exc:
        print(f'앱 게임 PID 확인 실패: {exc}')
    try:
        import ctypes
        print(f'이 스크립트 관리자 권한: {bool(ctypes.windll.shell32.IsUserAnAdmin())}')
    except Exception:
        pass
    for pid in pids:
        print(f'\n== PID {pid}')
        try:
            import win32api, win32con, win32process
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            try:
                value = win32process.GetPriorityClass(handle)
                mask, system = win32process.GetProcessAffinityMask(handle)
                print(f'① pywin32 GetPriorityClass(제한 권한): 0x{value:X} = {pp.name(value)} · 선호도 0x{mask:X}/0x{system:X}')
            finally:
                handle.Close()
        except Exception as exc:
            print(f'① pywin32 실패: {exc}')
        for label, access in (('② ctypes 제한 권한(0x1000)', 0x1000), ('③ ctypes 일반 조회(0x400)', 0x400)):
            value, error = pp.api_priority(pid, access)
            print(f'{label}: ' + (f'0x{value:X} = {pp.name(value)}' if value else f'실패 — {error}'))
        base = listed[pid][1]
        print(f'④ 프로세스 목록 기본 우선순위: {base} = {pp.name(pp.CLASS_OF_BASE.get(base)) if base in pp.CLASS_OF_BASE else "알 수 없음"}')
        try:
            out = subprocess.run(['powershell', '-NoProfile', '-Command',
                                  f'(Get-Process -Id {pid}).PriorityClass; (Get-Process -Id {pid}).BasePriority'],
                                 capture_output=True, text=True, timeout=15)
            print('⑤ PowerShell PriorityClass / BasePriority: ' + ' / '.join(out.stdout.split()) + (f' (오류 {out.stderr.strip()[:120]})' if out.returncode else ''))
        except Exception as exc:
            print(f'⑤ PowerShell 실패: {exc}')
        reading = pp.read(pid)
        print(f'→ 앱 판정(①과 같은 API + ④ 목록 교차 확인): {pp.describe(reading)}')
    print('\n작업 관리자 값과 다른 경로가 있으면 그 줄을 알려 주세요. (이 스크립트는 아무것도 바꾸지 않아요.)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
