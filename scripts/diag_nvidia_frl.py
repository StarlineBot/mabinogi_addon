"""그래픽 효율(최적화 명세 13.6) 개발 실측: NVIDIA 프로필 최대 프레임 읽기·쓰기·원복. Windows에서 실행한다.

실행(앱과 같은 권한으로 — 앱은 관리자 실행. 관리자 없이도 한 번 돌려 권한 필요 여부를 본다):
    uv run python -m scripts.diag_nvidia_frl                 # 그래픽카드·프로필·현재 값만 읽기(변경 없음)
    uv run python -m scripts.diag_nvidia_frl --write 400     # 400으로 쓰고 다시 읽기(원래 값은 화면에 출력)
    uv run python -m scripts.diag_nvidia_frl --restore none  # 설정 지우기(원래 '설정 없음'이던 경우)
    uv run python -m scripts.diag_nvidia_frl --restore 120   # 원래 값으로 되돌리기
    uv run python -m scripts.diag_nvidia_frl --own-profile-test  # 앱 프로필에 전체 경로 등록이 되는지(가짜 경로, 끝나면 지움)
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
    parser.add_argument('--own-profile-test', action='store_true')
    args = parser.parse_args()
    if args.own_profile_test:
        return own_profile_test()
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


def own_profile_test():
    """게임 프로필이 없는 PC에서 앱이 하는 일을 가짜 경로로 재현: 프로필 만들기 → 전체 경로 등록 → 그 경로로 찾기·읽기 → 지우기."""
    from mabinogi_addon.system.nvidia_drs import FrameLimit, OWN_PROFILE, api
    fake = r'C:\StarlineFrlTest\Client.exe'
    nv = api()
    limit = FrameLimit(nv)
    with nv.session() as session:
        before = nv.find_application(session, fake)
        before = nv.profile_name(session, before) if before is not None else None
    print('쓰기 전 가짜 경로 프로필:', before or '(없음)', '(앱은 마비노기·앱 프로필이 아니면 쓰지 않음)')
    try:
        limit.write([fake], 400)  # 마비노기 프로필이 아니므로 앱 프로필을 만들고 전체 경로를 등록한다
    except Exception as exc:
        print('앱 프로필 만들기·등록 실패:', exc)
        with nv.session() as session:
            own = nv.find_profile(session, OWN_PROFILE)
            if own is not None:
                nv.delete_profile(session, own)
                nv.save(session)
                print('남은 앱 프로필을 지웠어요.')
        return
    with nv.session() as session:
        found = nv.find_application(session, fake)
        print('쓴 뒤 가짜 경로 프로필:', nv.profile_name(session, found) if found is not None else '(없음)')
    print('쓴 뒤 다시 읽기:', limit.read([fake]))
    limit.write([fake], None)
    with nv.session() as session:
        print('지운 뒤 앱 프로필:', '(남아 있음)' if nv.find_profile(session, OWN_PROFILE) is not None else '(없음)')


if __name__ == '__main__':
    main()
