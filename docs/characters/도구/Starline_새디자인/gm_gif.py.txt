import cv2,numpy as np,glob
from PIL import Image,ImageDraw,ImageFont
G="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/제미나이걷기/앱크기/"; N="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/새걷기/앱크기/"
def pil(p): a=cv2.imdecode(np.fromfile(p,np.uint8),-1); return Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
STEP=round(74.8*0.165/1.15)
rows=[("제미나이 — 받은 순서 0~11",[G+f"gwalk_{i}.png" for i in range(12)]),
      ("제미나이 — 바꾼 순서 0·1·2·3·8·10·6 (발 번갈아)",[G+f"gwalk_{i}.png" for i in (0,1,2,3,8,10,6)]),
      ("참고: GPT 새 걷기 2~9",[N+f"walk12_{i}.png" for i in range(2,10)])]
T=56; W=1000; RH=320; fr=[]
for t in range(T):
    can=Image.new("RGB",(W,RH*3),(236,236,236)); d=ImageDraw.Draw(can)
    for r,(lab,seq) in enumerate(rows):
        p=seq[t%len(seq)]; x=40+(t*STEP)%(W-300)
        im=pil(p); can.paste(im,(x,r*RH+RH-6-im.size[1]),im)
        d.text((6,r*RH+4),lab+f"   ({p.split('_')[-1][:-4]}번)",fill=(50,50,50),font=font)
    fr.append(can)
H=fr[0].size[1]; mont=Image.new("RGB",(W,H*len(fr)))
for i,f in enumerate(fr): mont.paste(f,(0,H*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in fr]
out="/home/user/mabinogi_addon/docs/characters/assets/Starline/Starline_제미나이걷기_확인.gif"
q[0].save(out,save_all=True,append_images=q[1:],duration=170,loop=0); print(out)
