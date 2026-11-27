import sys,os,shutil,numpy as np,cv2
sys.path.insert(0,sys.argv[1]); from vcore import *
F8=load(V+"8_웅크리기_구석앉기.gif"); F9=load(V+"9_일어나기.gif")
def bb(a): m=a[...,3]>128; ys,xs=np.where(m); return ys.min(),ys.max(),xs.min(),xs.max()
a8=bb(F8[-1]); a9=bb(F9[0]); r=(a8[1]-a8[0])/(a9[1]-a9[0])
print("8 끝 bbox",a8,"9 처음 bbox",a9,"배율",round(r,3))
# 9 → 8 좌표: 크기 r, 아래·가운데 맞춤
cy9,cx9=a9[1],(a9[2]+a9[3])/2; cy8,cx8=a8[1],(a8[2]+a8[3])/2
Hc,Wc=900,600; ox,oy=120,140   # 넉넉한 공통 캔버스(8 좌표 + 여백)
def to_canvas(a,M): return cv2.warpAffine(a,M,(Wc,Hc),flags=cv2.INTER_LINEAR,borderValue=(0,0,0,0))
M8=np.float32([[1,0,ox],[0,1,oy]])
M9=np.float32([[r,0,cx8-r*cx9+ox],[0,r,cy8-r*cy9+oy]])
C8=[to_canvas(a,M8) for a in F8]; C9=[to_canvas(a,M9) for a in F9]
# 확인: 8 처음(서기) 발 아래 vs 9 끝(서기) 발 아래
fb=lambda a: np.where((a[...,3]>128).any(1))[0].max()
print("땅(발 아래 y): 8 처음",fb(C8[0]),"8 끝(앉음)",fb(C8[-1]),"9 처음",fb(C9[0]),"9 끝(서기)",fb(C9[-1]))
hd=lambda a: np.where((a[...,3]>128).any(1))[0].min()
print("머리 위 y: 8 처음",hd(C8[0]),"9 끝",hd(C9[-1]),"키 8처음",fb(C8[0])-hd(C8[0]),"9끝",fb(C9[-1])-hd(C9[-1]))
np.save(sys.argv[1]+"sit_c.npy",np.array([0]))
import pickle; pickle.dump((C8,C9),open(sys.argv[1]+"sit.pkl","wb"))

# 9를 끝으로 갈수록 서서히 보정: 땅 713에, 키 529에 맞춤(처음 장은 8 끝과 그대로 같게)
fbv=fb(C9[-1]); dy=fb(C8[0])-fbv; sc=(fb(C8[0])-hd(C8[0]))/(fbv-hd(C9[-1])); N=len(C9); out9=[]
for i,a in enumerate(C9):
    t=i/(N-1); s=1+(sc-1)*t; cx=Wc/2
    M=np.float32([[s,0,cx-s*cx],[0,s,fbv-s*fbv+dy*t]]); out9.append(cv2.warpAffine(a,M,(Wc,Hc),flags=cv2.INTER_LINEAR,borderValue=(0,0,0,0)))
print("보정 뒤 9 끝 땅",fb(out9[-1]),"키",fb(out9[-1])-hd(out9[-1]),"/ 9 처음 땅",fb(out9[0]))
# 서기 끝 가로 위치도 8 처음과 맞춤(마지막 몇 장만 서서히)
cxs=lambda a: np.where((a[...,3]>128)[fb(a)-30:fb(a)+1].any(0))[0].mean()
dx=cxs(C8[0])-cxs(out9[-1]); print("9 끝 발 가로 차",round(dx,1))
out9=[cv2.warpAffine(a,np.float32([[1,0,dx*i/(N-1)],[0,1,0]]),(Wc,Hc),borderValue=(0,0,0,0)) for i,a in enumerate(out9)]
# 앉은 높이 더 올리기(사용자 11-27): 원래 뜬 정도에 비례해 LIFT만큼 더 — 뜨기 시작하면 서서히, 내려오면 서서히
LIFT=float(sys.argv[2]) if len(sys.argv)>2 else 40.0
G=fb(C8[0]); end8=G-fb(C8[-1]); start9=G-fb(out9[0])
def lifted(fr,base):
    res=[]
    for a in fr:
        f=np.clip((G-fb(a))/max(base,1),0,1); res.append(cv2.warpAffine(a,np.float32([[1,0,0],[0,1,-LIFT*f]]),(Wc,Hc),flags=cv2.INTER_LINEAR,borderValue=(0,0,0,0)))
    return res
C8=lifted(C8,end8); out9=lifted(out9,start9)
print("뜬 높이(원본 px): 원래",end8,"→",end8+LIFT)
k=K*HW0/headw(F8[0])
U=np.any([a[...,3]>20 for a in C8+out9],axis=0); yy,xx=np.where(U); box=(yy.min(),yy.max()+1,xx.min(),xx.max()+1)
for name,fr in (("8_웅크리기_구석앉기",C8),("9_일어나기",out9)):
    d=OUT+name+"/"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
    for i,a in enumerate(fr): imwrite(d+f"{i:02d}.png",scaled(a[box[0]:box[1],box[2]:box[3]],k))
print("공통 틀",scaled(C8[0][box[0]:box[1],box[2]:box[3]],k).shape)
