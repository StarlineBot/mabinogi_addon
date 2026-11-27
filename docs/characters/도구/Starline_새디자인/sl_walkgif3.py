import cv2,numpy as np,glob
from PIL import Image,ImageDraw,ImageFont
N="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/새걷기/앱크기/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
STEP=round(74.8*0.165/1.15)
rows=[("오른쪽 — 순서대로 2~9",[f"walk12_{i}" for i in range(2,10)],STEP),
      ("왼쪽 — 순서대로 2~9",[f"walkL12_{i}" for i in range(2,10)],-STEP),
      ("왼쪽 — 바꾼 순서 2·3·4·5·6·8·7",[f"walkL12_{i}" for i in (2,3,4,5,6,8,7)],-STEP)]
T=56; W=1000; RH=330; fr=[]
for t in range(T):
    can=Image.new("RGB",(W,RH*3),(236,236,236)); d=ImageDraw.Draw(can)
    for r,(lab,seq,step) in enumerate(rows):
        n=seq[t%len(seq)]; x0=60 if step>0 else W-260
        x=x0+(t*step)%(W-320)*(1 if step>0 else 1) if step>0 else x0-(t*-step)%(W-320)
        im=pil(N+n+".png"); can.paste(im,(int(x),r*RH+RH-6-im.size[1]),im)
        # 제자리
        d.text((6,r*RH+4),lab+f"   ({n.split('_')[-1]}번)",fill=(50,50,50),font=font)
    fr.append(can)
H=fr[0].size[1]; mont=Image.new("RGB",(W,H*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,H*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out="/home/user/mabinogi_addon/docs/characters/assets/Starline/Starline_새걷기_순서비교.gif"
q[0].save(out,save_all=True,append_images=q[1:],duration=170,loop=0); print(out)
