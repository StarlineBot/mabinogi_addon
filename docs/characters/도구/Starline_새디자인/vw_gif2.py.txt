import cv2,numpy as np,glob
from PIL import Image,ImageDraw,ImageFont
V="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/영상걷기/앱크기/"; D2="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/앱크기/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
TICK=0.055   # 0.165 = 3틱, 0.1 ≈ 2틱(0.11)
V2=V.replace("앱크기/","앱크기2/")
rows=[("2차(주머니·거만한 눈) — 8장·0.165초",[V2+f"vwalk_{i}.png" for i in range(8)],3),
      ("2차 — 14장·약 0.1초",[V2+f"vwalk14_{i}.png" for i in range(14)],2),
      ("1차 — 8장·0.165초",[V+f"vwalk_{i}.png" for i in range(8)],3)]
_old=[
      ("영상 걷기 — 14장·약 0.1초 (더 부드러운 판)",[V+f"vwalk14_{i}.png" for i in range(14)],2),
      ("참고: 지금 새디자인2 걷기 8장",[D2+f"walk_{i}.png" for i in range(8)],3)]
SPEED=74.8/1.15   # 그림 px/초
T=int(round(1.32*3/TICK)); W=1000; RH=320; fr=[]
for t in range(T):
    can=Image.new("RGB",(W,RH*3+20),(236,236,236)); d=ImageDraw.Draw(can)
    for r,(lab,seq,ticks) in enumerate(rows):
        p=seq[(t//ticks)%len(seq)]; x=40+int((t*TICK*SPEED)%(W-300))
        im=pil(p); can.paste(im,(x,r*RH+RH-6-im.size[1]),im); d.text((6,r*RH+4),lab,fill=(50,50,50),font=font)
    fr.append(can)
H=fr[0].size[1]; mont=Image.new("RGB",(W,H*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,H*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out="/home/user/mabinogi_addon/docs/characters/assets/Starline/Starline_영상걷기2_확인.gif"
q[0].save(out,save_all=True,append_images=q[1:],duration=55,loop=0); print(out,len(fr))
