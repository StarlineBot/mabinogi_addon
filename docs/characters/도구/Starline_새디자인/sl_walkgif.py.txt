import cv2,numpy as np,glob
from PIL import Image,ImageDraw,ImageFont
O="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/"; N=O+"새걷기/앱크기/"; OLD=O+"앱크기/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
STEP=round(74.8*0.165/1.15)   # 앱 걷기 속도(그림 px/장)
seq=[("stand_pocket",0)]*6+[("walk12_0",0),("walk12_1",0)]
for r in range(3):
    for i in range(2,10): seq.append((f"walk12_{i}",STEP))
seq+= [("walk12_10",0),("walk12_11",0)]+[("stand_pocket",0)]*6
W=1100; fr=[]; x=60
inplace_new=[f"walk12_{i}" for i in range(2,10)]; inplace_old=[f"walk_{i}" for i in range(8)]
for t,(n,dx) in enumerate(seq):
    x+=dx; can=Image.new("RGB",(W,700),(236,236,236)); d=ImageDraw.Draw(can)
    im=pil(N+n+".png"); can.paste(im,(x,330-im.size[1]),im)
    d.text((6,4),"새 서 있기(주머니) → 돌기 → 걷기 → 돌기 → 서 있기 (앱 속도 0.165초·앱 걷기 빠르기)",fill=(50,50,50),font=font); d.text((6,22),n,fill=(110,110,110),font=font)
    # 아래: 제자리 비교
    cols=[("새 걷기(제자리)",N+inplace_new[t%8]+".png"),("지금 새디자인2 걷기",OLD+inplace_old[t%8]+".png"),("새 서 있기",N+"stand_pocket.png"),("걷기 0번",N+"walk12_0.png"),("걷기 11번",N+"walk12_11.png"),("새디자인2 서 있기",OLD+"stand_0.png")]
    for k,(lab,p) in enumerate(cols):
        im=pil(p); cx=k*183+92; can.paste(im,(cx-im.size[0]//2,690-im.size[1]),im); d.text((k*183+4,360),lab,fill=(50,50,50),font=font)
    fr.append(can)
H=fr[0].size[1]; mont=Image.new("RGB",(W,H*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,H*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out="/home/user/mabinogi_addon/docs/characters/assets/Starline/Starline_새걷기_확인.gif"
q[0].save(out,save_all=True,append_images=q[1:],duration=170,loop=0); print(out,len(fr),"장 STEP",STEP)
