import cv2,numpy as np,glob,sys
from PIL import Image,ImageDraw,ImageFont
O="/home/user/mabinogi_addon/docs/characters/assets/Starline/영상/앱크기/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
ST=[pil(O+f"stand_{i:02d}.png") for i in range(30)]
A8=[pil(O+f"8_웅크리기_구석앉기/{i:02d}.png") for i in range(30)]; A9=[pil(O+f"9_일어나기/{i:02d}.png") for i in range(30)]
seq=ST[:10]+A8+A8[-1:]*8+A9+ST[:10]; fr=[]
for t,a in enumerate(seq):
    can=Image.new("RGB",(360,380),(236,236,236)); d=ImageDraw.Draw(can)
    can.paste(a,(180-a.size[0]//2,370-a.size[1]),a); d.text((6,4),"서기 → 구석 앉기(더 높이) → 일어나기 → 서기",fill=(50,50,50),font=font)
    d.line([(10,370),(350,370)],fill=(170,170,170)); fr.append(can)
mont=Image.new("RGB",(360,380*len(fr))); [mont.paste(f,(0,380*i)) for i,f in enumerate(fr)]
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out="/home/user/mabinogi_addon/docs/characters/assets/Starline/Starline_구석높이_확인.gif"; q[0].save(out,save_all=True,append_images=q[1:],duration=100,loop=0); print(out)
