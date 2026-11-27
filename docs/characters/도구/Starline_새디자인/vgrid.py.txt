import cv2,numpy as np,glob,os
from PIL import Image,ImageDraw,ImageFont
O="/home/user/mabinogi_addon/docs/characters/assets/Starline/영상/앱크기/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],13)
M=[("0 서 있기",[O+f"stand_{i:02d}.png" for i in range(30)])]
for d in sorted([x for x in os.listdir(O) if os.path.isdir(O+x)],key=lambda s:int(s.split("_")[0])):
    M.append((d.replace("_"," ",1),sorted(glob.glob(O+d+"/*.png"))))
cols=5; cw,ch=200,370; rows=(len(M)+cols-1)//cols; fr=[]
imgs=[[pil(p) for p in ps] for _,ps in M]
for t in range(30):
    can=Image.new("RGB",(cols*cw,rows*ch),(236,236,236)); d=ImageDraw.Draw(can)
    for j,(lab,_) in enumerate(M):
        r,c=divmod(j,cols); im=imgs[j][t%len(imgs[j])]
        can.paste(im,(c*cw+cw//2-im.size[0]//2,r*ch+ch-8-im.size[1]),im); d.text((c*cw+4,r*ch+4),lab,fill=(50,50,50),font=font)
    fr.append(can)
W,H=fr[0].size; mont=Image.new("RGB",(W,H*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,H*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out="/home/user/mabinogi_addon/docs/characters/assets/Starline/Starline_영상전체동작.gif"
q[0].save(out,save_all=True,append_images=q[1:],duration=100,loop=0); print(out,len(M),"동작")
