"""Build full-word references from visually labeled native screenshots."""

import hashlib
import json
from pathlib import Path

import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.detect.dorcha_reader import prepare, _normalize

ROOT = Path(__file__).resolve().parents[1]
# Coordinates refer to original pixels, not resized chat previews.
SOURCES = [
    (0, "스크린샷 2026-10-06 223724.png", (714, 890, 28, 23)),
    (0, "2026-10-11_111640.png", (1333, 36, 28, 23)),
    # 2026-10-27 타 사용자 문의(4K): 가장자리 안티앨리어싱이 기존 '0'과 1px 달라 0.849로 거절되던 렌더링
    (0, "2026-10-24_dorcha_report_4K.png", (1112, 1736, 28, 23)),
    *[(value, f"스크린샷 2026-10-16 {stamp}.png", None) for value, stamp in (
        (1, "211435"), (2, "211426"), (3, "211420"), (4, "212007"),
        (5, "211352"), (6, "211343"), (7, "210815"), (8, "210805"),
        (9, "211332"), (10, "210734"), (11, "210757"), (12, "210747"),
        (13, "211456"), (14, "211458"), (15, "211914"),
    )],
    # 0.30.2: 4K(3840×2160) — 숫자 높이는 같지만 '1' 획이 3px(창 모드 4px)로 가늘어 기존 참조와 0.68~0.88로만 맞았다.
    # image55(15)는 세트에 넣지 않고 따로 검증한다(처음 보는 4K 화면에서도 읽히는지).
    *[(value, f"mabinogi_2026_10_30_{stamp}.png", (1342, 57, 28, 23)) for value, stamp in (
        (15, "213520"), (14, "213927"), (13, "213942"), (11, "214016"), (10, "214051"), (9, "214648"),
    )],
]


def main():
    refs, labels, provenance = [], [], []
    target = ROOT / "src/mabinogi_addon/detect/templates/dorcha"
    target.mkdir(parents=True, exist_ok=True)
    for value, name, box in SOURCES:
        path = ROOT / "tests/data" / name
        frame = image_io.imread(path)
        assert frame is not None
        if box is None:
            x, y = (931, 929) if frame.shape[0] == 1436 else (933, 931)
            box = (x + 8, y + 17, 28, 23)
        x, y, w, h = box
        ink = prepare(frame[y:y+h, x:x+w])
        assert ink is not None, name
        refs.append(_normalize(ink))
        labels.append(value)
        provenance.append(dict(value=value, file=name, box=list(box),
                               sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    np.savez_compressed(target / "refs.npz", refs=np.stack(refs), labels=np.array(labels))
    (target / "sources.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(refs)} full-word references, values 0..15")


if __name__ == "__main__":
    main()
