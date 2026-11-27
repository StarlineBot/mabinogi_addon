import sys,os,shutil,numpy as np,cv2
sys.path.insert(0,sys.argv[1]); from vcore import *
name="5_모자마술"; F=load(V+name+".gif"); R=F[0]; s=HW0/headw(R); k=K*s
fade={15:0.8,16:0.55,17:0.3,18:0.1}
out=[]
for i,a in enumerate(F):
    a=a.copy(); al=a[...,3].astype(np.float32)
    m=(al>40).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(m); big=1+int(np.argmax(st[1:,4]))
    if i>=14:   # 몸과 떨어진 것(박쥐·연기) 점점 사라지게
        f=fade.get(i,0.0 if i>18 else 1.0); al[(l!=big)&(l>0)]*=f
    # 오른쪽 끝에 닿은 모자 챙: 끝에서 24px 안쪽부터 부드럽게 사라지게
    W=a.shape[1]; ramp=np.clip((W-1-np.arange(W))/24.0,0,1)[None,:]
    if (al[:, -2:]>40).any(): al=al*np.where(np.arange(a.shape[0])[:,None]>220,ramp,1.0)
    a[...,3]=al.clip(0,255).astype(np.uint8); out.append(a)
U=np.any([a[...,3]>20 for a in out],axis=0); yy,xx=np.where(U); box=(yy.min(),yy.max()+1,xx.min(),xx.max()+1)
d=OUT+name+"/"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
for i,a in enumerate(out): imwrite(d+f"{i:02d}.png",scaled(a[box[0]:box[1],box[2]:box[3]],k))
print("done",len(out))
