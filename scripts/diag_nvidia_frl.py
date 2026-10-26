"""그래픽 효율(최적화 명세 13.6) 개발 실측: NVIDIA 프로필 최대 프레임 읽기·쓰기·원복. Windows에서 실행한다.

실행(앱과 같은 권한으로 — 앱은 관리자 실행. 관리자 없이도 한 번 돌려 권한 필요 여부를 본다):
    uv run python -m scripts.diag_nvidia_frl                 # 그래픽카드·프로필·현재 값만 읽기(변경 없음)
    uv run python -m scripts.diag_nvidia_frl --write 400     # 400으로 쓰고 다시 읽기(원래 값은 화면에 출력)
    uv run python -m scripts.diag_nvidia_frl --restore none  # 설정 지우기(원래 '설정 없음'이던 경우)
    uv run python -m scripts.diag_nvidia_frl --restore 120   # 원래 값으로 되돌리기
확인할 것:
  ① NVAPI 호출이 되는지(함수·구조체 버전), ② 관리자 없이 쓰기가 되는지, ③ NVIDIA 제어판 '프로그램 설정'에 같은 값이 보이는지,
  ④ 게임 실행 중에 쓰면 바로 반영되는지(FPS 표시로 로딩 화면 400 상한) 아니면 게임을 다시 켜야 하는지.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('exe', nargs='?', help='게임 실행 파일 이름(기본: 앱에 등록한 이름)')
    parser.add_argument('--write', type=int)
    parser.add_argument('--restore')
    args = parser.parse_args()
    from mabinogi_addon import config
    from mabinogi_addon.system.nvidia_drs import FrameLimit, api
    from mabinogi_addon.system.optimization import WindowsOptimization
    import ctypes
    exe = (args.exe or config.load_game_exe() or '').lower()
    if not exe:
        sys.exit('게임 실행 파일을 지정해 주세요(예: Client.exe).')
    print('관리자 권한:', bool(ctypes.windll.shell32.IsUserAnAdmin()))
    nv = api()
    print('그래픽카드:', nv.gpu_names())
    backend = WindowsOptimization()
    names = backend._frl_names(exe)  # 앱과 같은 규칙: 실행 중이거나 기억한 전체 경로만
    print('앱이 쓰는 이름:', names)
    with nv.session() as session:
        for name in names + [exe]:  # 비교용으로 이름만으로 찾은 프로필도 보여준다(앱은 쓰지 않음)
            profile = nv.find_application(session, name)
            print(f'  {name} → 프로필:', nv.profile_name(session, profile) if profile is not None else '(없음)')
    limit = FrameLimit(nv)
    print('현재 최대 프레임:', limit.read(names), '(None=설정 없음, 0=끔)')
    if args.write is not None:
        limit.write(names, args.write)
        print('쓴 뒤 다시 읽기:', limit.read(names))
    if args.restore is not None:
        limit.write(names, None if args.restore.lower() == 'none' else int(args.restore))
        print('원복 뒤 다시 읽기:', limit.read(names))


if __name__ == '__main__':
    main()
