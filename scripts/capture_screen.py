"""개발용: 화면/영역을 PNG로 저장해 탐지 테스트 데이터를 모은다.

게임을 띄운 Windows에서 실행한다. mss로 캡처(맥/Windows 공용).

예:
    # 전체 화면 1장 → tests/data/capture_1.png
    uv run python scripts/capture_screen.py

    # 특정 영역(x y w h)만
    uv run python scripts/capture_screen.py --region 1770 400 220 550 --name buff

    # 2초 간격 5장(점멸 구간 등 연속 수집)
    uv run python scripts/capture_screen.py --count 5 --interval 2 --name buff
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import mss
import numpy as np

OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="화면 캡처 → PNG")
    parser.add_argument(
        "--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"), default=None
    )
    parser.add_argument("--name", default="capture", help="파일 이름 접두사")
    parser.add_argument("--count", type=int, default=1, help="장수")
    parser.add_argument("--interval", type=float, default=1.0, help="간격(초)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with mss.mss() as sct:
        if args.region:
            x, y, w, h = args.region
            area = {"left": x, "top": y, "width": w, "height": h}
        else:
            area = sct.monitors[1]  # 주 모니터 전체

        for i in range(1, args.count + 1):
            shot = sct.grab(area)
            img = np.array(shot)[:, :, :3]  # BGRA → BGR
            out = OUT_DIR / f"{args.name}_{i}.png"
            cv2.imwrite(str(out), img)  # cv2는 BGR로 저장
            print("저장:", out)
            if i < args.count:
                time.sleep(args.interval)

    print(f"\n{OUT_DIR} 에 저장됨. 버프 상태창/디버프 줄이 잘 보이는 걸 고르세요.")


if __name__ == "__main__":
    main()
