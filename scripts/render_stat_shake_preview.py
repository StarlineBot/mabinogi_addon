"""Render actual stat bars into a standalone animated design comparison.

Run with QT_QPA_PLATFORM=offscreen; no game, capture, audio or config IO.
"""

import argparse
import base64
import json
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.stat_overlay import StatBarOverlay


def render_bar(sid, scale, ratio):
    bar = StatBarOverlay(sid, scale)
    try:
        bar._locked = True
        bar._relayout()
        bar.set_value(ratio)
        image = QImage(bar.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        bar.render(image)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert image.save(buffer, "PNG")
        return image, "data:image/png;base64," + base64.b64encode(buffer.data()).decode("ascii")
    finally:
        bar.close()
        bar.deleteLater()


HTML = """<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>체력바 흔들림 시안</title>
<style>
*{box-sizing:border-box;letter-spacing:0}body{margin:0;background:#17191c;color:#eee;font:14px system-ui,sans-serif}
main{max-width:1380px;margin:auto;padding:24px}h1{font-size:22px;margin:0 0 20px}h2{font-size:17px;margin:0}
header{display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin-bottom:24px}
label{display:flex;gap:8px;align-items:center}select,button{background:#30343a;color:#fff;border:1px solid #737982;border-radius:4px;padding:8px;font:inherit}
.variants{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
article{border:1px solid #565c65;border-radius:6px;overflow:hidden}article>div:first-child{padding:16px;min-height:90px}
p{color:#bdc3cc;margin:8px 0 0}.stage{overflow:auto;background:#22262b;height:246px;padding:16px}
.bars{width:max-content;min-width:100%;height:208px;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:14px;padding:0 14px}
.slot{position:relative;line-height:0}.baseline{position:absolute;top:-4px;bottom:-4px;left:0;border-left:1px solid #8b9199;opacity:.35}
img{display:block;max-width:none}footer{margin-top:24px;color:#b4bac3}
@media(max-width:900px){.variants{grid-template-columns:1fr}main{padding:16px}}
</style>
<main><h1>체력바 저값 경고</h1>
<header><label>배율 <select id="scale"><option value="0.5">50%</option><option value="1">100%</option><option value="1.5" selected>150%</option><option value="3">300%</option></select></label>
<label>상태 <select id="state"><option value="one">HP 저값</option><option value="two">HP · MP 저값</option><option value="all">HP · MP · STA 저값</option><option value="normal">정상</option></select></label>
<label><input id="pause" type="checkbox">일시정지</label></header>
<section class="variants"></section>
<footer>시안 비교용이며 앱 설정에 추가되는 선택 항목은 아닙니다.</footer></main>
<script>
const assets=__ASSETS__;
const variants=[{name:'A · 약하게',amplitude:2,burst:.32,rest:1.7},
 {name:'B · 기본 후보',amplitude:3,burst:.4,rest:1.4},
 {name:'C · 또렷하게',amplitude:4,burst:.48,rest:1.3}];
const scale=document.querySelector('#scale'), state=document.querySelector('#state'), pause=document.querySelector('#pause');
const panels=variants.map(v=>{
 const article=document.createElement('article');
 article.innerHTML=`<div><h2>${v.name}</h2><p>좌우 ${v.amplitude}px · ${v.burst}초 2회 왕복 · ${v.rest}초 정지</p></div><div class="stage"><div class="bars"></div></div>`;
 document.querySelector('.variants').append(article);
 const imgs=['hp','mp','sta'].map(sid=>{
  const slot=document.createElement('div');slot.className='slot';
  const guide=document.createElement('span');guide.className='baseline';slot.append(guide);
  const img=document.createElement('img');img.alt=sid.toUpperCase();slot.append(img);
  article.querySelector('.bars').append(slot);return img;
 });return {v,imgs};
});
let epoch=performance.now(),handle=null;
function selected(index){return state.value==='all'||(index===0&&state.value!=='normal')||(index===1&&state.value==='two')}
function updateAssets(){panels.forEach(({imgs})=>imgs.forEach((img,i)=>{
 const a=assets[scale.value][['hp','mp','sta'][i]][selected(i)?'low':'normal'];
 img.src=a.src;img.width=a.width;img.height=a.height;
}));}
function frame(now){
 const t=(now-epoch)/1000;
 panels.forEach(({v,imgs})=>imgs.forEach((img,i)=>{
  const phase=t%(v.burst+v.rest);
  const x=!pause.checked&&selected(i)&&phase<v.burst
   ? Math.sin(phase/v.burst*4*Math.PI)*v.amplitude*Number(scale.value):0;
  img.style.transform=`translateX(${x}px)`;
 }));
 handle=!pause.checked&&state.value!=='normal'?requestAnimationFrame(frame):null;
}
function refresh(){if(handle!==null)cancelAnimationFrame(handle);epoch=performance.now();updateAssets();frame(epoch);}
[scale,state,pause].forEach(el=>el.addEventListener('change',refresh));
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(handle!==null)cancelAnimationFrame(handle);handle=null;}else refresh();});
refresh();
</script></html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/stat-shake-preview"))
    parser.add_argument("--gif", action="store_true", help="Also render a short animated comparison with ffmpeg")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assets = {}
    images = {}
    sheet = QImage(1080, 220, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#22262b"))
    painter = QPainter(sheet)
    painter.setPen(QColor("white"))
    for scale in (.5, 1, 1.5, 3):
        key = str(scale)
        assets[key] = {}
        for index, sid in enumerate(("hp", "mp", "sta")):
            assets[key][sid] = {}
            for state, ratio in (("normal", .85), ("low", .25)):
                image, src = render_bar(sid, scale, ratio)
                images[scale, sid, state] = image
                assets[key][sid][state] = dict(src=src, width=image.width(), height=image.height())
                if scale == 1.5 and state == "low":
                    for column, label in enumerate(("A: +/-2px", "B: +/-3px", "C: +/-4px")):
                        painter.drawText(24 + column * 360, 30, label)
                        painter.drawImage(24 + column * 360, 50 + index * 46, image)
    painter.end()
    assert sheet.save(str(args.output / "comparison.png"))
    target = args.output / "index.html"
    target.write_text(HTML.replace("__ASSETS__", json.dumps(assets)), encoding="utf-8")
    if args.gif:
        render_gif(args.output, images)
    app.processEvents()
    print(target)


def render_gif(output, images):
    variants = ((2, .32, 1.7), (3, .4, 1.4), (4, .48, 1.3))
    with TemporaryDirectory(prefix="stat-shake-") as folder:
        for frame in range(180):
            t = frame / 30
            canvas = QImage(1080, 240, QImage.Format.Format_RGB32)
            canvas.fill(QColor("#22262b"))
            painter = QPainter(canvas)
            painter.setPen(QColor("white"))
            for column, (amplitude, burst, rest) in enumerate(variants):
                x = 24 + column * 360
                painter.drawText(x, 28, f"{'ABC'[column]}: +/-{amplitude}px / {burst}s + {rest}s rest")
                for index, sid in enumerate(("hp", "mp", "sta")):
                    low = t < 4.5 and (index == 0 or t >= 2)
                    since = .4 if index == 0 else 2.4
                    phase = (t - since) % (burst + rest)
                    offset = (math.sin(phase / burst * 4 * math.pi) * amplitude * 1.5
                              if low and t >= since and phase < burst else 0)
                    painter.drawImage(x + round(offset), 48 + index * 46,
                                      images[1.5, sid, "low" if low else "normal"])
            painter.drawText(24, 220, "HP low / all low / recovery - 150% scale")
            painter.end()
            assert canvas.save(str(Path(folder) / f"{frame:04}.png"))
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-framerate", "30", "-i", str(Path(folder) / "%04d.png"),
            "-filter_complex", "split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0",
            str(output / "comparison.gif"),
        ], check=True)


if __name__ == "__main__":
    main()
