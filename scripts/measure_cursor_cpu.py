"""마우스 커서 표시 효과별 CPU 측정(마우스 커서 명세 4절 3항) — Windows에서 사람이 실행한다.

    uv run python -m scripts.measure_cursor_cpu [--seconds 15]

효과마다 정해진 시간 동안 **마우스를 계속 크게 움직여 주세요**(원을 그리듯). 이 스크립트는 커서 위치를 읽기만 하고
마우스를 움직이거나 누르지 않는다. 앱 설정 파일은 바꾸지 않는다(측정용 설정만 메모리에서 바꿈).
측정값: 이 프로세스의 CPU 시간 / 경과 시간 → '작업 관리자 기준(전체 코어 대비) %'와 '코어 1개 기준 %'.
게임과 앱을 함께 켠 실제 상황과 다를 수 있으니, 4K 화면에서 앱을 끈 상태로 재고 결과 표를 status에 붙인다.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

CASES = (
    ("원", dict(shape="ring", tail="none")),
    ("스코프(짧은 십자)", dict(shape="scope", tail="none")),
    ("스코프(화면 선)", dict(shape="lines", tail="none")),
    ("꼬리: 점", dict(shape="none", tail="dots")),
    ("꼬리: 선", dict(shape="none", tail="line")),
    ("꼬리: 무지개 선", dict(shape="none", tail="rainbow")),
    ("꼬리: 반짝이", dict(shape="none", tail="sparkle")),
    ("원 + 선 꼬리(길게)", dict(shape="ring", tail="line", tailLength="long")),
    ("흔들기(모양·꼬리 없음, 흔들어 찾기 켬) — 빠르게 좌우로 흔들어 주세요", dict(shape="none", tail="none", shake=True)),
    ("원 + 반짝이 + 흔들어 찾기", dict(shape="ring", tail="sparkle", shake=True)),
    ("원 · 마우스 멈춤(움직이지 마세요)", dict(shape="ring", tail="line")),
)


class _Always:
    def is_game_active(self):
        return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--only", type=str, default="", help="측정할 번호(쉼표, 예: 1,9)")
    args = parser.parse_args(argv)
    global CASES
    if args.only:
        picks = [int(n) - 1 for n in args.only.split(",") if n.strip().isdigit()]
        CASES = tuple(CASES[i] for i in picks if 0 <= i < len(CASES))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon import config
    from mabinogi_addon.ui.cursor_overlay import CursorFx

    config.save_cursor_fx = lambda *a, **k: None  # 측정은 설정 파일을 바꾸지 않는다
    config.load_cursor_fx = lambda *a, **k: {}
    app = QApplication(sys.argv)
    fx = CursorFx(_Always())
    cores = os.cpu_count() or 1
    results = []
    state = {"i": -1, "t0": 0.0, "c0": 0.0}

    def next_case():
        if state["i"] >= 0:
            wall = time.perf_counter() - state["t0"]
            cpu = time.process_time() - state["c0"]
            name = CASES[state["i"]][0]
            results.append((name, cpu / wall * 100 / cores, cpu / wall * 100))
            print(f"  → {name}: 전체 {results[-1][1]:.2f}% · 코어 1개 {results[-1][2]:.1f}%", flush=True)
            st = fx.stats
            print(f"    초당: 틱 {st['ticks']/wall:.0f} · 움직임 {st['moved']/wall:.0f} · 원 이동 {st['ring_moves']/wall:.0f}"
                  f" · 꼬리 갱신 {st['tail_updates']/wall:.0f} · 그리기 {st['paints']/wall:.0f} · 창 크기 변경 {st['resizes']/wall:.1f}"
                  f" · 꼬리 창 {fx._tail.width()}×{fx._tail.height()} · 타이머 {fx._timer.interval()}ms", flush=True)
        state["i"] += 1
        if state["i"] >= len(CASES):
            fx.shutdown()
            print("\n| 효과 | CPU(전체 코어 대비) | 코어 1개 기준 |\n|---|---|---|")
            for name, total, one in results:
                print(f"| {name} | {total:.2f}% | {one:.1f}% |")
            print(f"\n코어 {cores}개 · 효과당 {args.seconds:.0f}초. 위 표를 개발에 보내 주세요.")
            app.quit()
            return
        name, changes = CASES[state["i"]]
        still = "멈춤" in name
        # 안내는 3초 전에 미리(예전엔 측정 시작 때 나와, 앞 단계대로 움직이던 손이 멈춤 측정에 섞였다)
        print(f"\n[{state['i'] + 1}/{len(CASES)}] {name} — 3초 뒤 {args.seconds:g}초 측정 · "
              + ("지금 마우스에서 손을 떼 주세요." if still else "지금부터 마우스를 계속 크게 움직여 주세요."), flush=True)
        fx.update_settings(**{**dict(enabled=True, shake=False, size=40, opacity=100, tailLength="normal"), **changes})

        def start():
            print("  측정 중… " + ("마우스를 움직이지 마세요." if "멈춤" in name else "마우스를 계속 크게 움직여 주세요."),
                  flush=True)
            fx.stats.clear()
            state["t0"], state["c0"] = time.perf_counter(), time.process_time()
            QTimer.singleShot(int(args.seconds * 1000), next_case)
        QTimer.singleShot(int(min(3.0, args.seconds) * 1000), start)

    QTimer.singleShot(0, next_case)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
