# 받은 장(파일)마다 색이 조금씩 달라(GPT 장마다 톤 흔들림) → 걷기 장(파일 6) 기준으로 장 단위 색 맞춤
import sys,os,json,glob,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite
R="/home/user/mabinogi_addon/"; D=R+"docs/characters/assets/Starline/"; O=D+"의상/새디자인/"
m=json.load(open(D+"의상/전체프레임_v2/칸_목록.json",encoding="utf-8")); SRC={1:6,2:4,3:5,4:2,5:3,6:1}
src=O+"다시_앱크기/"; dst=O+"장색맞춤/"; os.makedirs(dst,exist_ok=True)
byfile={}
for x in m: byfile.setdefault(SRC[x["part"]],[]).append(x["frame"])
C=[45,130,210]
def wts(L):
    w=np.stack([np.exp(-((L-c)/40.)**2) for c in C],-1); return w/w.sum(-1,keepdims=True)
def stats(names):
    px=np.concatenate([cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2LAB).astype(float)[a[...,3]>200] for a in (imread(src+n+".png",-1) for n in names)])
    w=wts(px[:,0]); mu=np.array([(px*w[:,i:i+1]).sum(0)/w[:,i].sum() for i in range(3)])
    sd=np.array([np.sqrt(((px-mu[i])**2*w[:,i:i+1]).sum(0)/w[:,i].sum()) for i in range(3)]); return mu,sd
# 사이모션10 다시 그림(사용자 11-27): 모션마다 한 장 → 그 장끼리 묶어 맞춤
for f in list(byfile): byfile[f]=[n for n in byfile[f] if not n.startswith("motion_tidy10")]
byfile["A"]=[f"motion_tidy10a_{i}" for i in range(12)]; byfile["B"]=[f"motion_tidy10b_{i}" for i in range(12)]
mt,st=stats(byfile[6])
# 밝기 옮김 = 띠별(어두운·중간·밝은) L 차이의 평균 — 전체 평균은 그림 내용(망토 비율 등)에 휘둘림
dL={f:float(np.mean(mt[:,0]-stats(n)[0][:,0])) for f,n in byfile.items() if n and f!=6}; print("장 밝기 옮김",{k:round(v,1) for k,v in dL.items()})
for f,names in sorted([kv for kv in byfile.items() if kv[1]],key=lambda kv:str(kv[0])):
    ms,ss=stats(names); k=np.clip(st/np.maximum(ss,1),0.85,1.18)
    print("파일",f,"평균 차(L,a,b 띠별)",np.round(ms-mt,1).tolist())
    for n in names:
        a=imread(src+n+".png",-1); lab=cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2LAB).astype(float); w=wts(lab[...,0])
        # 색(a·b)만 띠별 평균 맞춤, 밝기(L)는 장 전체 한 번만 옮김 — 띠별 L·표준편차까지 맞추면 머리 잔결이 10% 진해져
        # 자글자글(사용자 11-27 사이 모션 10)
        o=lab.copy()
        if f!=6:
            o[...,1:]=sum(w[...,i:i+1]*(lab[...,1:]-ms[i][1:]+mt[i][1:]) for i in range(3))
            o[...,0]=lab[...,0]+(dL[f] if f in dL else 0)
        b=a.copy(); b[...,:3]=cv2.cvtColor(np.clip(o,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); imwrite(dst+n+".png",b)
