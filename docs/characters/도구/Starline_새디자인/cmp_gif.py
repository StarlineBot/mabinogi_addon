import cv2,numpy as np,glob,sys
from PIL import Image,ImageDraw,ImageFont
D="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인/새디자인_앱크기/"; OLD="/tmp/claude-0/-home-user-mabinogi-addon/5eadae52-74cf-5bff-9103-5e037310a3e4/scratchpad/oldtidy/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
cols=[("서 있기(참고)",None,"stand_0"),("어깨·금장 — 이전",OLD,"motion_tidy10a"),("어깨·금장 — 새 그림",D,"motion_tidy10a"),("소매·팔찌 — 이전",OLD,"motion_tidy10b"),("소매·팔찌 — 새 그림",D,"motion_tidy10b")]
fr=[]
for t in range(12):
    can=Image.new("RGB",(5*220,340),(236,236,236)); d=ImageDraw.Draw(can)
    for k,(lab,src,key) in enumerate(cols):
        im=pil(D+"stand_0.png") if src is None else pil(src+f"{key}_{t}.png")
        can.paste(im,(k*220+110-im.size[0]//2,332-im.size[1]),im); d.text((k*220+4,4),lab,fill=(50,50,50),font=font)
        if src: d.text((k*220+4,22),f"{t}번",fill=(90,90,90),font=font)
    fr.append(can)
W,H=fr[0].size; mont=Image.new("RGB",(W,H*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,H*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out="/home/user/mabinogi_addon/docs/characters/assets/Starline/Starline_사이모션10_다시그림_비교.gif"
q[0].save(out,save_all=True,append_images=q[1:],duration=130,loop=0,optimize=False); print(out)
# 같은 장을 GIF로 저장했을 때 원본과의 차(이전 방식 vs 지금 방식)
old=[f.quantize(colors=200,method=Image.Quantize.MEDIANCUT).convert("RGB") for f in fr[:4]]
new=[x.convert("RGB") for x in q[:4]]
e=lambda A,B: float(np.mean([np.abs(np.asarray(a,float)-np.asarray(b,float)).mean() for a,b in zip(A,B)]))
# 장 사이 팔레트 흔들림: 같은 위치(서 있기 칸, 안 움직임)에서 장끼리 차
st=lambda L:[np.asarray(x,float)[40:330,0:220] for x in L]
print("서 있기 칸(그림 안 바뀜) 장끼리 색 흔들림 — 이전 방식 %.2f, 지금 %.2f"%(np.mean([np.abs(a-b).mean() for a,b in zip(st(old)[:-1],st(old)[1:])]),np.mean([np.abs(a-b).mean() for a,b in zip(st(new)[:-1],st(new)[1:])])))
print("원본과의 차 — 이전 %.2f, 지금 %.2f"%(e(old,fr[:4]),e(new,fr[:4])))
