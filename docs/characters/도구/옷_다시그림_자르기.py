"""옷 전체 다시 그림 → 장 매칭 확인·칸 자르기·앱 크기(기본 같은 프레임 키 × 머리 맞춤)."""
import sys, os, json, numpy as np, cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread, imwrite, _tight, scaled
from scripts.silhouette import best_scale
ch,outfit,cols,motmap=sys.argv[1],sys.argv[2],int(sys.argv[3]),json.loads(sys.argv[4])
R="/home/user/mabinogi_addon/"; D=R+f"docs/characters/assets/{ch}/의상/"; O=D+outfit+"/"; A=R+f"src/mabinogi_addon/assets/characters/{ch}/"
m=json.load(open(D+"전체프레임_v2/칸_목록.json",encoding="utf-8")); parts=sorted({x["part"] for x in m}); rows=4
def keyblack(a):
    if a.shape[2]==4: return a
    b,g,r=[a[...,i].astype(int) for i in range(3)]
    pure=(b>200)&(g>120)&(g<205)&(r<25)            # 칸 선 색(BGR 250,170,0)
    line=np.zeros(pure.shape,bool)
    for x in np.where(pure.mean(0)>0.5)[0]: line[:,max(0,x-6):x+7]=True   # 세로 선(±6px 번짐까지)
    for y in np.where(pure.mean(1)>0.5)[0]: line[max(0,y-6):y+7,:]=True   # 가로 선
    dark=(np.maximum(np.maximum(b,g),r)<=14)
    n,lab=cv2.connectedComponents(dark.astype(np.uint8),connectivity=4)
    seed=np.zeros_like(dark); seed[0,:]=seed[-1,:]=seed[:,0]=seed[:,-1]=True
    seed|=cv2.dilate(line.astype(np.uint8),np.ones((5,5),np.uint8))>0
    keep=set(np.unique(lab[seed&dark]))-{0}
    bg=np.isin(lab,list(keep))|line
    # 머리카락 사이 등에 갇힌 검정 틈(사용자 11-26): 순검정(≤14) 덩어리 8px 이상도 배경
    nn,lab2,st2,_=cv2.connectedComponentsWithStats(dark.astype(np.uint8),connectivity=4)
    pocket=np.isin(lab2,[i for i in range(1,nn) if st2[i,4]>=8])
    bg|=pocket
    # 틈 가장자리의 검정 번짐(≤30)도 1px
    near=cv2.dilate(pocket.astype(np.uint8),np.ones((3,3),np.uint8))>0
    bg|=near&(np.maximum(np.maximum(b,g),r)<=30)
    al=np.where(bg,0,255).astype(np.uint8)
    return np.dstack([a,al])
def gridlines(a):
    b,g,r=[a[...,i].astype(int) for i in range(3)]
    pure=(b>200)&(g>120)&(g<205)&(r<25)
    if a.shape[2]==4: pure&=a[...,3]>128
    line=np.zeros(pure.shape,bool)
    for x in np.where(pure.mean(0)>0.5)[0]: line[:,max(0,x-6):x+7]=True
    for y in np.where(pure.mean(1)>0.5)[0]: line[max(0,y-6):y+7,:]=True
    return line
def cleanup(a):
    a=keyblack(a).copy(); a[gridlines(a),3]=0
    al=a[...,3].astype(int); al[al>=235]=255; al[al<=20]=0
    hard=(al>=235).astype(np.uint8); d=cv2.distanceTransform(1-hard,cv2.DIST_L2,5); al[(al<235)&(d>2)]=0; a[...,3]=al.astype(np.uint8); a[a[...,3]==0,:3]=0; return a
def cellsof(a):
    H,W=a.shape[:2]; ch_,cw=H/rows,W/cols; out=[]
    for k in range(cols*rows):
        r,c=divmod(k,cols); out.append(a[int(r*ch_)+4:int((r+1)*ch_)-4,int(c*cw)+4:int((c+1)*cw)-4].copy())
    return out
def mask(c): return cv2.resize((c[...,3]>128).astype(np.uint8),(60,64),interpolation=cv2.INTER_AREA)>0
# 매칭 확인
tm={p:[mask(c) for c in cellsof(imread(D+f"전체프레임_v2/전체프레임_{p}.png",-1))] for p in parts}
import glob,re
files=sorted(int(re.search(r"전체프레임_(\d+)_다시",f).group(1)) for f in glob.glob(O+"전체프레임_*_다시.png"))
score={}
for fno in files:
    a=cleanup(imread(O+f"전체프레임_{fno}_다시.png",-1)); cs=[mask(c) for c in cellsof(a)]
    for q in parts:
        n=len([x for x in m if x["part"]==q])
        score[(fno,q)]=float(np.mean([(cs[k]&tm[q][k]).sum()/max(1,(cs[k]|tm[q][k]).sum()) for k in range(n)]))
SRC={}; used=set()
for (fno,q),v in sorted(score.items(),key=lambda kv:-kv[1]):
    if q in SRC or fno in used: continue
    SRC[q]=fno; used.add(fno)
print("파일별 점수",{f:{q:round(score[(f,q)],2) for q in parts} for f in files})
print("템플릿 장 → 파일(일치)",{q:(SRC[q],round(score[(SRC[q],q)],3)) for q in sorted(SRC)},"남는 파일",[f for f in files if f not in used])
if len(SRC)!=len(parts): print("!! 장 빠짐",[q for q in parts if q not in SRC]); sys.exit(1)
top=lambda x:x[:int(x.shape[0]*.42)]
HAT=len(sys.argv)>5 and sys.argv[5]=="hat"
if len(sys.argv)>6:
    SRC={int(k):v for k,v in json.loads(sys.argv[6]).items()}; parts=sorted(SRC); print("직접 지정",SRC)
out=O+"다시_앱크기/"; os.makedirs(out,exist_ok=True); rep=[]; todo=[]
for p in parts:
    cs=cellsof(cleanup(imread(O+f"전체프레임_{SRC[p]}_다시.png",-1)))
    for x in [e for e in m if e["part"]==p]:
        cell=cs[x["cell"]]; mm=(cell[...,3]>40).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(mm)
        name=x["frame"]
        if name.startswith("motion:"):
            lab,i=name.split(":")[1].rsplit("_",1); name=motmap[lab]+"_"+i
        if n<=1: rep.append((name,"빈 칸")); continue
        big=1+int(np.argmax(st[1:,4])); cell[~np.isin(l,[i for i in range(1,n) if st[i,4]>=st[big,4]*0.02])]=0
        f=_tight(cell); bp=A+name+".png"
        if not os.path.exists(bp): rep.append((name,"기본 없음")); continue
        base=_tight(imread(bp,-1)); k0=base.shape[0]/f.shape[0]; sc=best_scale(top(base),top(scaled(f,k0)),.7,1.2,101)
        todo.append((name,f,k0,sc,base.shape[0]))
side=lambda n:n.startswith("walk_")          # 옆모습은 모자가 머리를 덜 가려 보정을 따로
med=float(np.median([t[3] for t in todo if not side(t[0])])) if HAT else 1.0
meds=float(np.median([t[3] for t in todo if side(t[0])] or [1.0])) if HAT else 1.0
print("머리 배율 중앙값 앞",round(med,3),"옆",round(meds,3),"(모자 보정)" if HAT else "")
# 옆모습(걷기)은 '걷기 키 ÷ 서 있기 키'를 기본 캐릭터와 같게(QA ③) — 모자 때문에 머리 맞춤만으론 어긋남
wf=1.0
if HAT and any(side(t[0]) for t in todo):
    st=[t for t in todo if t[0]=="stand_0"][0]; sh=st[1].shape[0]*st[2]*min(1.15,max(0.85,st[3]/med))
    wh=float(np.median([t[1].shape[0]*t[2]*min(1.15,max(0.85,t[3]/meds)) for t in todo if side(t[0])]))
    bw=float(np.median([_tight(imread(A+f"walk_{i}.png",-1)).shape[0] for i in range(8)])); bs=_tight(imread(A+"stand_0.png",-1)).shape[0]
    wf=(bw/bs)/(wh/sh); print("걷기 비율 맞춤",round(wh/sh,3),"→",round(bw/bs,3),"배",round(wf,3))
for name,f,k0,sc,bh in todo:
    s2=min(1.15,max(0.85,sc/(meds if side(name) else med)))*(wf if side(name) else 1.0); g=scaled(f,k0*s2); imwrite(out+name+".png",g); rep.append((name,round(s2,3),g.shape[0],bh))
print("칸",len(rep),"문제",[r for r in rep if not isinstance(r[1],float)])
print("머리보정 ±6% 밖",[r for r in rep if isinstance(r[1],float) and abs(r[1]-1)>0.06])
