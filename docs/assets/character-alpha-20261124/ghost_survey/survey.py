import os, sys, random, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "src")
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtCore import QRectF
import numpy as np
app = QGuiApplication([])
from mabinogi_addon.character import brain as br
from mabinogi_addon.ui import pet_window as pw

OUT = sys.argv[1]
DT = 1 / 60


def scenarios(b, t):
    seq = []

    def run(sec, front=False):
        nonlocal t
        end = t + sec
        while t < end:
            b.tick(t, front)
            seq.append((t, b.frame(t)))
            t += DT

    run(2)
    x, y = b.pos
    b.press(t, x, y - 150); b.release(t); run(4)                  # 서서 클릭
    for mood in ("normal", "explain", "think", "happy"):          # 긴 말(분위기별)
        b.talk(t, 24, mood); run(6)
    b.talk(t, 6, "normal"); run(3)                                 # 짧은 말
    b._next_extra = t + 0.5; run(20)                               # 대기 동작
    b._next_extra = t + 0.2; run(1.0); b.talk(t, 20, "normal"); run(6)   # 대기 동작 중 말
    b.notify(t); run(3)                                            # 알림
    x, y = b.pos; b.press(t, x, y - 150)                           # 끌기 → 놓기 → 착지
    for i in range(20):
        b.move(t, x + i * 5, y - 150 - i * 8); run(DT)
    b.release(t); run(4)
    hx = b.pos[0]                                                  # 쓰다듬기
    for _ in range(10):
        for dx in (0, 30, 0, -30):
            b.hover(t, hx + dx, True); run(0.05)
    b.hover(t, hx, False); run(4)
    run(12, front=True); run(5, front=False)                       # 구석·앉기 → 일어나기
    return seq


k = br.FIGURE_H / pw.FRAME_DIR_H


def placed(img):
    W, H = pw.WIN_W, pw.WIN_H
    canvas = QImage(W, H, QImage.Format.Format_ARGB32)
    canvas.fill(0)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    w, h = img.width() * k, img.height() * k
    dx = dy = 0.0
    a = img.text("anchor")
    if a:
        dx, dy = (float(v) * k for v in a.split(","))
    p.drawImage(QRectF(W / 2 - w / 2 + dx, H - pw.FOOT - h + dy, w, h), img)
    p.end()
    arr = np.frombuffer(canvas.constBits(), np.uint8).reshape(H, canvas.bytesPerLine() // 4, 4)[:, :W]
    return arr.copy()


report = {}
for name, prof in br.PROFILES.items():
    frames = pw.load_frames(name, prof)
    b = br.Brain(br.Floor(0, 1920, 1040), profile=prof, rng=random.Random(1))
    seq = scenarios(b, 100.0)
    pairs = {}
    prev = None
    for _t, f in seq:
        if prev is not None and f != prev:
            pairs.setdefault((prev, f), [0, b.covered(prev, f)])[0] += 1
        prev = f
    rows = []
    for (old, new), (n, cov) in sorted(pairs.items()):
        if not cov:
            continue
        if old not in frames or new not in frames:
            rows.append({"pair": f"{old}->{new}", "missing": True})
            continue
        A, B = placed(frames[old]), placed(frames[new])
        ma, mb = A[..., 3] > 128, B[..., 3] > 128
        union = (ma | mb).sum()
        iou = (ma & mb).sum() / union if union else 1.0
        ghost = (ma ^ mb).sum() / max(1, mb.sum())
        rows.append({"pair": f"{old}->{new}", "n": n, "iou": round(float(iou), 3), "ghost": round(float(ghost), 3)})
        mix = A.astype(float)
        alpha = B[..., 3:4] / 255 * 0.5
        mix[..., :3] = mix[..., :3] * (1 - alpha) + B[..., :3] * alpha
        mix[..., 3] = np.maximum(A[..., 3], B[..., 3] * 0.5)
        img = QImage(mix.astype(np.uint8).tobytes(), pw.WIN_W, pw.WIN_H, pw.WIN_W * 4, QImage.Format.Format_ARGB32).copy()
        img.save(os.path.join(OUT, f"{name}__{old}__{new}.png"))
    report[name] = {"covered": rows, "all_pairs": len(pairs)}
json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for name, r in report.items():
    print("==", name, "transitions", r["all_pairs"], "covered", len(r["covered"]))
    for row in sorted(r["covered"], key=lambda x: x.get("iou", 0)):
        print("  ", row)
