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
mt,st=stats(byfile[6])
for f,names in sorted(byfile.items()):
    ms,ss=stats(names); k=np.clip(st/np.maximum(ss,1),0.85,1.18)
    print("파일",f,"평균 차(L,a,b 띠별)",np.round(ms-mt,1).tolist())
    for n in names:
        a=imread(src+n+".png",-1); lab=cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2LAB).astype(float); w=wts(lab[...,0])
        o=sum(w[...,i:i+1]*((lab-ms[i])*k[i]+mt[i]) for i in range(3)) if f!=6 else lab
        b=a.copy(); b[...,:3]=cv2.cvtColor(np.clip(o,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); imwrite(dst+n+".png",b)
