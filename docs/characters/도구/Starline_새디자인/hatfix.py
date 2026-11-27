import sys,os,shutil,numpy as np,cv2
sys.path.insert(0,sys.argv[1]); from vcore import *
name="5_모자마술"; F=load(V+name+".gif"); R=F[0]; s=HW0/headw(R); k=K*s
fade={15:0.8,16:0.55,17:0.3,18:0.1}
# 박쥐가 오른쪽 토끼귀를 치고 가는 순간(14번 장)부터 별이 튐(사용자 11-27)
HIT=(285,95); T0=14; DIRS=[(-75,1.0,16),(-30,0.85,13),(-120,0.75,11),(10,0.6,9)]   # (각도°, 거리비, 크기px)
GOLD=(79,213,255); INK=(58,36,62)
def star_pts(cx,cy,R,rot):
    t=np.arange(10)*np.pi/5+rot; r=np.where(np.arange(10)%2==0,R,R*0.45)
    return np.stack([cx+r*np.sin(t),cy-r*np.cos(t)],1)
def stars(a,i):
    t=i-T0
    if t<0 or t>5: return a
    p=[0.35,0.75,1.0,1.1,1.15,1.2][t]; sz=[0.6,1.1,1.0,0.9,0.8,0.7][t]; op=[1,1,1,0.85,0.5,0.2][t]
    H,W=a.shape[:2]; SS=4; lay=np.zeros((H*SS,W*SS,4),np.uint8)
    for ang,dist,R in DIRS:
        rad=np.radians(ang); cx=HIT[0]+np.cos(rad)*55*dist*p; cy=HIT[1]+np.sin(rad)*55*dist*p
        pts=(star_pts(cx,cy,R*sz,t*0.35+ang)*SS).astype(np.int32)
        cv2.fillPoly(lay,[pts],(*INK,255)); 
        inner=(star_pts(cx,cy,max(1,R*sz-2.2),t*0.35+ang)*SS).astype(np.int32); cv2.fillPoly(lay,[inner],(*GOLD,255))
    lay=cv2.resize(lay,(W,H),interpolation=cv2.INTER_AREA).astype(np.float32); A=lay[...,3:]/255*op
    o=a.astype(np.float32); ab=o[...,3:]/255
    o[...,:3]=lay[...,:3]/np.maximum(lay[...,3:]/255,1e-3)*A+o[...,:3]*(1-A); o[...,3:]=(A+ab*(1-A))*255
    return o.clip(0,255).astype(np.uint8)
out=[]
for i,a in enumerate(F):
    a=a.copy(); al=a[...,3].astype(np.float32)
    m=(al>40).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(m); big=1+int(np.argmax(st[1:,4]))
    if i>=14:   # 몸과 떨어진 것(박쥐·연기) 점점 사라지게
        f=fade.get(i,0.0 if i>18 else 1.0); al[(l!=big)&(l>0)]*=f
    # 오른쪽 끝에 닿은 모자 챙: 끝에서 24px 안쪽부터 부드럽게 사라지게
    W=a.shape[1]; ramp=np.clip((W-1-np.arange(W))/24.0,0,1)[None,:]
    if (al[:, -2:]>40).any(): al=al*np.where(np.arange(a.shape[0])[:,None]>220,ramp,1.0)
    a[...,3]=al.clip(0,255).astype(np.uint8)
    a=stars(a,i); out.append(a)
U=np.any([a[...,3]>20 for a in out],axis=0); yy,xx=np.where(U); box=(yy.min(),yy.max()+1,xx.min(),xx.max()+1)
d=OUT+name+"/"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
for i,a in enumerate(out): imwrite(d+f"{i:02d}.png",scaled(a[box[0]:box[1],box[2]:box[3]],k))
print("done",len(out))
