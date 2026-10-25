"""설정 안내 그림을 원본 스크린샷에서 만들어 assets/guide에 넣는다(개발 도구, 영역은 mabinogi_addon.guide_images).

실행: uv run python -m scripts.build_guide_images
"""
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from mabinogi_addon import guide_images, image_io  # noqa: E402

SOURCE = ROOT / 'tests/data/스크린샷 2026-10-25 233749.png'
OUT = ROOT / 'src/mabinogi_addon/assets/guide'


def main():
    source = image_io.imread(SOURCE)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in guide_images.IMAGES:
        image = guide_images.render(source, name)
        ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        assert ok
        (OUT / f'{name}.jpg').write_bytes(data.tobytes())
        print(name, image.shape[1], 'x', image.shape[0], len(data) // 1024, 'KB')


if __name__ == '__main__':
    main()
