# 영상 걷기(초록 배경 GIF) → 초록 빼기·장별 측정
import sys,os,glob,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imwrite,_tight,scaled
S=sys.argv[1]; O="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/영상걷기/"
def key(img):
    f=img.astype(np.float32); b,g,r=f[...,0],f[...,1],f[...,2]
    spill=g-np.maximum(r,b)                      # 초록 우세
    al=np.clip(1-(spill-25)/70,0,1)              # 25 이하 = 몸, 95 이상 = 배경
    m=(al>0.5).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(m); bi=1+int(np.argmax(st[1:,4]))
    keep=np.isin(l,[i for i in range(1,n) if st[i,4]>=st[bi,4]*0.02]); al=np.where(keep|(al<0.5),al,0); al[~cv2.dilate(keep.astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)]=0
    g2=np.minimum(g,np.maximum(r,b)+8)          # 가장자리 초록 번짐 빼기
    out=np.dstack([b,g2,r,al*255]).clip(0,255).astype(np.uint8); return out
fs=sorted(glob.glob(S+"vf/f*.png")); K=[key(cv2.imread(f)) for f in fs]
rows=[]
for i,k in enumerate(K):
    al=k[...,3]>128; ys,xs=np.where(al); top=ys.min(); bot=ys.max(); H=bot-top
    mid=al[top+int(H*.45):top+int(H*.6)]; body=np.median(np.where(mid)[1])
    fx=np.where(al[bot-int(H*.08):bot+1].any(0))[0]
    rows.append((i,top,bot,int(body),int(fx.max()-body),int(body-fx.min())))
import json; json.dump([list(map(int,r)) for r in rows],open(S+"vw_meas.json","w"))
for r in rows: print(r)
np.save(S+"vw_keyed.npy",np.stack(K))
