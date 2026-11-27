# 제미나이 걷기 12장(어두운 단색 배경) → 배경 빼기·칸 자르기
import sys,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite,_tight,scaled
O="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/제미나이걷기/"
a=imread(O+"걷기_12장_원본.png",-1)[...,:3]; H,W=a.shape[:2]
lab=cv2.cvtColor(a,cv2.COLOR_BGR2LAB).astype(np.float32)
border=np.concatenate([lab[:4].reshape(-1,3),lab[-4:].reshape(-1,3),lab[:,:4].reshape(-1,3),lab[:,-4:].reshape(-1,3)])
bg=np.median(border,0); d=np.linalg.norm(lab-bg,axis=-1)
print("배경 Lab",bg.round(1),"배경 흩어짐 p99 %.1f"%np.percentile(np.linalg.norm(border-bg,axis=1),99))
t0,t1=float(sys.argv[1]),float(sys.argv[2])
near=(d<t1).astype(np.uint8)
n,l=cv2.connectedComponents(near,connectivity=4)
edge=set(np.unique(np.r_[l[0],l[-1],l[:,0],l[:,-1]]))-{0}
# 바깥과 이어진 '배경에 가까운' 영역 + 그 안의 큰 덩어리(머리 사이 틈) 
outside=np.isin(l,list(edge))
st=cv2.connectedComponentsWithStats(near,connectivity=4)[2]
pocket=np.isin(l,[i for i in range(1,n) if st[i,4]>=40 and i not in edge])&(d<t0+3)
reg=outside|pocket
al=np.full((H,W),255,np.float32); al[reg]=np.clip((d[reg]-t0)/(t1-t0),0,1)*255
al=cv2.GaussianBlur(al,(3,3),0); al[(d<t0)&reg]=0
# 가장자리 배경색 빼기(반투명 픽셀 색 복원)
A=al[...,None]/255.; bgc=cv2.cvtColor(np.uint8([[bg]]),cv2.COLOR_LAB2BGR)[0,0].astype(np.float32)
rgb=np.where(A>0.02,(a.astype(np.float32)-(1-A)*bgc)/np.maximum(A,1e-3),0); rgb=np.clip(rgb,0,255)
out=np.dstack([rgb,al]).astype(np.uint8); imwrite(O+"키잉.png",out)
# 칸: 가로 4 · 세로 3 — 알파 투영 빈 곳으로
m=out[...,3]>40
def gaps(p,mn=8):
    z=p<0.002; runs=[]; s=None
    for i,v in enumerate(z):
        if v and s is None: s=i
        if not v and s is not None:
            if i-s>=mn: runs.append((s,i))
            s=None
    if s is not None: runs.append((s,len(z)))
    return runs
print("cols",gaps(m.mean(0)),"rows",gaps(m.mean(1)))
