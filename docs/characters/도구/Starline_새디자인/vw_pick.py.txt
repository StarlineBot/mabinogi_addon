import numpy as np,cv2,sys,os
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imwrite,_tight,scaled
S=sys.argv[1]; O=sys.argv[2]; pre=sys.argv[3]
K=np.load(S+"vw_keyed.npy"); N=len(K)
low=[(k[int(k.shape[0]*.6):,:,3]>128) for k in K]; full=[k[...,3]>128 for k in K]
g=[cv2.cvtColor(k[...,:3],cv2.COLOR_BGR2GRAY).astype(float) for k in K]
dif=lambda i,j: np.abs(g[i]-g[j])[full[i]|full[j]].mean()
sc={p:np.mean([dif(i,i+p) for i in range(N-p)]) for p in range(8,18)}; print("주기 후보",{p:round(v,1) for p,v in sc.items()})
p0=min(sc,key=sc.get); P=(p0+min([p0-1,p0+1],key=lambda q:sc.get(q,1e9)))/2 if abs(sc.get(p0-1,1e9)-sc[p0])<2.5 or abs(sc.get(p0+1,1e9)-sc[p0])<2.5 else p0
best=min(((dif(s,s+p),s,p) for p in {int(np.floor(P)),int(np.ceil(P))} for s in range(N-p)),key=lambda x:x[0]); _,s,p=best
picks=[s+int(round(j*P/8)) for j in range(8)]; print("주기 %.1f장(%.2f초)"%(P,P*0.1),"구간",s,"→",s+p,"이음매",round(best[0],1),"고른 장",picks)
os.makedirs(O,exist_ok=True); hs=[_tight(K[i]).shape[0] for i in picks]; k=283/np.median(hs)
for j,i in enumerate(picks): imwrite(O+f"{pre}_{j}.png",scaled(_tight(K[i]),k))
for j,i in enumerate(range(s,s+p)): imwrite(O+f"{pre}{p}_{j}.png",scaled(_tight(K[i]),k))
bots=[np.where(full[i].any(1))[0].max() for i in picks]; tops=[(b-np.where(full[i].any(1))[0].min())*k for b,i in zip(bots,picks)]
print("배율 %.3f"%k,"키",[round(t) for t in tops],"머리 흔들림 %.1fpx (%.1f%%)"%(max(tops)-min(tops),(max(tops)-min(tops))/283*100))
