# 털색 아이보리 v3: 장마다 '피부 표본(눈 아래 얼굴)'과 '머리 표본(분홍 중 피부와 먼 곳)'으로 피부/머리를 가르고,
# 이웃 픽셀끼리 고르게(자글자글 방지 — 사용자 11-27 '착지·어깨 금장이 자글자글') 칠함
import cv2,numpy as np,sys
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread
def _eyes(a):
    H=a.shape[0]; hsv=cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2HSV).astype(int)
    m=(hsv[...,0]>=15)&(hsv[...,0]<=32)&(hsv[...,1]>150)&(hsv[...,2]>150)&(a[...,3]>200); m[:int(H*.2)]=0; m[int(H*.45):]=0
    ys,xs=np.where(m)
    if len(ys)<20: return None           # 눈 감은 장
    return int(np.median(ys)),int(np.median(xs))
def hairw(img,top=0.32):
    H,W=img.shape[:2]; lab=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2LAB).astype(np.float32); L,A,B=lab[...,0],lab[...,1]-128,lab[...,2]-128
    C=np.hypot(A,B); ang=np.degrees(np.arctan2(B,A)); op=img[...,3]>200
    cand=op&(A>4)&(L>110)&(C<48)&(ang<45)
    e=_eyes(img); cy,cx=e if e else (int(H*.36),W//2)
    sk=np.zeros((H,W),bool)
    if e: sk[cy+4:cy+12,max(0,cx-10):cx+10]=True; sk&=cand&(L<215)
    if sk.sum()<15: sk=cand&(ang>31)&(C>22)
    f=np.stack([L/3.,A,B],-1)            # 밝기는 덜 보고 색 위주
    ms=f[sk].mean(0); cs=np.cov(f[sk].T)+np.eye(3)*4
    hr=cand.copy(); hr[:cy+14]=False; hr&=(ang<29)          # 아래쪽 긴 머리에서 덜 주황인 곳 = 머리 표본
    if hr.sum()<50: hr=cand&(ang<27)
    mh=f[hr].mean(0); ch=np.cov(f[hr].T)+np.eye(3)*4
    def md(mu,cv): d=f-mu; return np.einsum("...i,ij,...j->...",d,np.linalg.inv(cv),d)
    p=1/(1+np.exp((md(mh,ch)-md(ms,cs))/2))               # 머리일 확률
    p=np.where(cand,p,0).astype(np.float32)
    p=cv2.GaussianBlur(p,(5,5),0); p=np.clip((p-0.35)/0.3,0,1)*cand   # 이웃끼리 고르게
    p=np.where((C<20)&(L>185)&(C>8)&op,1.0,p)              # 옅고 밝은 머리
    ear=np.zeros_like(p); ear[:int(H*top)]=np.clip((C[:int(H*top)]-31)/4,0,1)
    return p*(1-ear)
def ivory2(img,ka=0.25,db=5,dl=2):
    w=cv2.GaussianBlur(hairw(img),(3,3),0)
    lab=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2LAB).astype(np.float32)
    t=lab.copy(); t[...,1]=128+(lab[...,1]-128)*ka; t[...,2]+=db; t[...,0]+=dl
    lab=lab*(1-w[...,None])+t*w[...,None]; o=img.copy(); o[...,:3]=cv2.cvtColor(np.clip(lab,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); return o
