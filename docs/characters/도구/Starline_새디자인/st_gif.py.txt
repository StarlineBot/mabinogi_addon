import cv2,numpy as np,glob
from PIL import Image,ImageDraw,ImageFont
A="/home/user/mabinogi_addon/docs/characters/assets/Starline/"; V=A+"영상/앱크기/"; W2=A+"의상/새디자인2/영상걷기/앱크기2/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
ST=[V+f"stand_{i:02d}.png" for i in range(30)]; WK=[W2+f"vwalk14_{i}.png" for i in range(14)]
SPEED=74.8/1.15; TICK=0.1
# 오른쪽: 서기 3초 → 걷기 2바퀴 → 서기 3초
seq=[(p,0) for p in ST]+[(WK[i%14],SPEED*TICK) for i in range(28)]+[(p,0) for p in ST]
W=900; fr=[]; x=430
for t,(p,dx) in enumerate(seq):
    x+=dx; can=Image.new("RGB",(W,360),(236,236,236)); d=ImageDraw.Draw(can)
    a=pil(ST[t%30]); can.paste(a,(40,350-a.size[1]),a); d.text((6,4),"서 있기 영상(0.1초 × 30장 반복)",fill=(50,50,50),font=font)
    b=pil(p); can.paste(b,(int(x)-b.size[0]//2,350-b.size[1]),b); d.text((330,4),"서기 → 걷기(영상 2차 14장) → 서기 (앱 빠르기)",fill=(50,50,50),font=font)
    fr.append(can)
H=fr[0].size[1]; mont=Image.new("RGB",(W,H*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,H*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out=A+"Starline_영상서있기_확인.gif"; q[0].save(out,save_all=True,append_images=q[1:],duration=100,loop=0); print(out,len(fr))
