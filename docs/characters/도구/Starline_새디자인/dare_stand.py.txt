import sys,os,shutil,glob,numpy as np,cv2
sys.path.insert(0,sys.argv[1]); from vcore import load,scaled,imwrite
from PIL import Image,ImageDraw,ImageFont
A="/home/user/mabinogi_addon/docs/characters/assets/"; V=A+"다래/영상/"
F=load(V+"0_서있기.gif"); bot=[np.where((a[...,3]>128).any(1))[0].max() for a in F]; top=[np.where((a[...,3]>128).any(1))[0].min() for a in F]
H=float(np.median(np.array(bot)-np.array(top))); k=282/H; G=max(bot)
def build(pin):
    out=[]
    for a,b in zip(F,bot):
        dy=(G-b) if pin else 0; out.append(cv2.warpAffine(a,np.float32([[1,0,0],[0,1,dy]]),(a.shape[1],a.shape[0]),borderValue=(0,0,0,0)))
    U=np.any([o[...,3]>20 for o in out],axis=0); yy,xx=np.where(U); return [scaled(o[yy.min():yy.max()+1,xx.min():xx.max()+1],k) for o in out]
hop=build(False); pin=build(True)
for nm,fr in (("앱크기/stand_hop",hop),("앱크기/stand_pin",pin)):
    d=V+nm+"/"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
    for i,a in enumerate(fr): imwrite(d+f"{i:02d}.png",a)
shutil.copy(sys.argv[1]+"vf/f000.png",V+"0_서있기_시작.png") if False else None
g=Image.open(V+"0_서있기.gif"); g.seek(0); g.convert("RGB").save(V+"0_서있기_시작.png")
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
pil=lambda a: Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
SL=[pil(cv2.imdecode(np.fromfile(A+f"Starline/영상/앱크기/stand_{i:02d}.png",np.uint8),-1)) for i in range(30)]
fr=[]
for t in range(60):
    can=Image.new("RGB",(660,350),(236,236,236)); d=ImageDraw.Draw(can)
    for c,(lab,im) in enumerate((("다래 — 받은 그대로(살짝 뜀)",pil(hop[t%30])),("다래 — 발 붙임(숨쉬기만)",pil(pin[t%30])),("참고: Starline 서 있기",SL[t%30]))):
        can.paste(im,(c*220+110-im.size[0]//2,340-im.size[1]),im); d.text((c*220+4,4),lab,fill=(50,50,50),font=font)
    d.line([(5,340),(655,340)],fill=(170,170,170)); fr.append(can)
mont=Image.new("RGB",(660,350*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,350*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out=A+"다래/다래_영상서있기_확인.gif"; q[0].save(out,save_all=True,append_images=q[1:],duration=100,loop=0); print(out)
