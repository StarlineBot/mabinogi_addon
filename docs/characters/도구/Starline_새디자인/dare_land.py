# 다래 4 착지: 끝에서 다시 떠오르는 구간을 땅에 붙여 '일어나 서기'로(사용자 11-27)
import sys,os,shutil,glob,numpy as np,cv2
sys.path.insert(0,sys.argv[1]); from vcore import load,scaled,imwrite
from PIL import Image,ImageDraw,ImageFont
V="/home/user/mabinogi_addon/docs/characters/assets/다래/영상/"
F=load(V+"4_착지.gif"); bot=[np.where((a[...,3]>128).any(1))[0].max() for a in F]
G=int(np.median(bot[9:16]))          # 앉아 있는 장의 땅
first=next(i for i in range(16,len(F)) if bot[i]<G-3)   # 다시 뜨기 시작하는 장
out=[]
for i,(a,b) in enumerate(zip(F,bot)):
    dy=(G-b) if i>=first-1 else 0
    out.append(cv2.warpAffine(a,np.float32([[1,0,0],[0,1,dy]]),(a.shape[1],a.shape[0]+80),borderValue=(0,0,0,0)))
print("땅",G,"붙이기 시작 장",first-1,"끝 장 내림",G-bot[-1],"px")
# 앱 크기: 서 있기 영상과 머리 폭 기준
ST=load(V+"0_서있기.gif")
def headw(a):
    m=a[...,3]>128; ys=np.where(m.any(1))[0]; t,b=ys.min(),ys.max(); band=m[t+int((b-t)*.30):t+int((b-t)*.38)]; xs=np.where(band.any(0))[0]; return xs.max()-xs.min()
H0=np.ptp(np.where((ST[0][...,3]>128).any(1))[0]); K=282/H0; k=283/np.ptp(np.where((out[-1][...,3]>128).any(1))[0])   # 끝 장(선 자세) 키 = 서 있기 키
U=np.any([o[...,3]>20 for o in out],axis=0); yy,xx=np.where(U)
d=V+"앱크기/4_착지/"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
fr=[scaled(o[yy.min():yy.max()+1,xx.min():xx.max()+1],k) for o in out]
for i,a in enumerate(fr): imwrite(d+f"{i:02d}.png",a)
def tight(a):
    ys,xs=np.where(a[...,3]>20); return a[ys.min():ys.max()+1,xs.min():xs.max()+1]
st=[scaled(tight(a),K) for a in ST]
print("키: 착지 끝",fr[-1].shape[0],"서 있기",st[0].shape[0],"머리폭 비",round(headw(ST[0])/headw(out[-1]),3))
font=ImageFont.truetype(glob.glob("/usr/share/fonts/**/*CJK*",recursive=True)[0],14)
pil=lambda a: Image.fromarray(cv2.cvtColor(a,cv2.COLOR_BGRA2RGBA))
seq=[("착지",pil(a)) for a in fr]+[("서 있기",pil(st[i])) for i in range(20)]
frames=[]
for lab,im in seq:
    can=Image.new("RGB",(300,380),(236,236,236)); can.paste(im,(150-im.size[0]//2,370-im.size[1]),im)
    ImageDraw.Draw(can).text((6,4),"다래 떨어지기·착지 → 서 있기",fill=(50,50,50),font=font); ImageDraw.Draw(can).line([(5,370),(295,370)],fill=(170,170,170)); frames.append(can)
mont=Image.new("RGB",(300,380*len(frames)))
for i,f in enumerate(frames): mont.paste(f,(0,380*i))
pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT); q=[f.quantize(palette=pal,dither=Image.Dither.NONE) for f in frames]
q[0].save("/home/user/mabinogi_addon/docs/characters/assets/다래/다래_착지_확인.gif",save_all=True,append_images=q[1:],duration=100,loop=0); print("ok")
