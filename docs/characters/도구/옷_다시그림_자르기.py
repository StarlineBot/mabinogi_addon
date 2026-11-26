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
SRC={p:p for p in parts}
for p in parts:
    a=cleanup(imread(O+f"전체프레임_{p}_다시.png",-1)); cs=[mask(c) for c in cellsof(a)]
    sc={q:np.mean([(cs[k]&tm[q][k]).sum()/max(1,(cs[k]|tm[q][k]).sum()) for k in range(len(cs))]) for q in parts}
    best=max(sc,key=sc.get); print(f"파일 {p}: 가장 닮은 템플릿 {best} ({sc[best]:.3f}) / 자기 {sc[p]:.3f}"); SRC[best]=p
if len(set(SRC.values()))!=len(parts): print("!! 매칭 겹침",SRC); sys.exit(1)
print("템플릿 장 → 파일",SRC)
top=lambda x:x[:int(x.shape[0]*.42)]
out=O+"다시_앱크기/"; os.makedirs(out,exist_ok=True); rep=[]
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
        base=_tight(imread(bp,-1)); k0=base.shape[0]/f.shape[0]; s=best_scale(top(base),top(scaled(f,k0)),.85,1.15,61); g=scaled(f,k0*s)
        imwrite(out+name+".png",g); rep.append((name,round(s,3),g.shape[0],base.shape[0]))
print("칸",len(rep),"문제",[r for r in rep if not isinstance(r[1],float)])
print("머리보정 ±6% 밖",[r for r in rep if isinstance(r[1],float) and abs(r[1]-1)>0.06])
