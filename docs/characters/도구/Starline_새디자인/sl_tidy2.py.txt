# 사이 모션 10 다시 그림(사용자 11-27, 모션마다 한 장 3열×4행) → 앱 크기(새 서 있기 배율 × 모션 공통 머리 맞춤)
import sys,numpy as np,cv2,statistics
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite,_tight,scaled
from scripts.silhouette import best_scale
R="/home/user/mabinogi_addon/"; O=R+"docs/characters/assets/Starline/의상/새디자인/"
t=open(R+"docs/characters/도구/옷_다시그림_자르기.py",encoding="utf-8").read(); rows,cols=4,4
exec("def "+t.split("\ndef ",1)[1].split("def mask(c)")[0])
out=O+"다시_앱크기/"; stand=imread(out+"stand_0.png",-1); top=lambda x:x[:int(x.shape[0]*.42)]
st_src=_tight(cellsof(cleanup(imread(O+"전체프레임_6_다시.png",-1)))[0])     # 받은 그림 서 있기(원본 크기)
for key,fn in (("motion_tidy10a","어깨금장_다시.png"),("motion_tidy10b","소매팔찌_다시.png")):
    a=cleanup(imread(O+"사이모션10/"+fn,-1)); H,W=a.shape[:2]; ch,cw=H/4,W/3; fr=[]
    for k in range(12):
        r,c=divmod(k,3); cell=a[int(r*ch)+3:int((r+1)*ch)-3,int(c*cw)+3:int((c+1)*cw)-3].copy()
        mm=(cell[...,3]>40).astype(np.uint8); n,l,stt,_=cv2.connectedComponentsWithStats(mm); b=1+int(np.argmax(stt[1:,4]))
        cell[~np.isin(l,[i for i in range(1,n) if stt[i,4]>=stt[b,4]*0.02])]=0; fr.append(_tight(cell))
    k0=stand.shape[0]/float(np.median([f.shape[0] for f in fr]))
    scs=[best_scale(top(stand),top(scaled(f,k0)),.85,1.15,61) for f in fr]; md=statistics.median(scs)
    for i,f in enumerate(fr): imwrite(out+f"{key}_{i}.png",scaled(f,k0*md))
    print(key,"키(원본)",[f.shape[0] for f in fr],"배율",round(k0,3),"머리 맞춤",round(md,3),"장별",[round(s,3) for s in scs])
