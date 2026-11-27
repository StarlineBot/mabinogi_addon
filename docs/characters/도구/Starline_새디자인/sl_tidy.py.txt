import sys,json,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite,_tight,scaled
from scripts.silhouette import best_scale
R="/home/user/mabinogi_addon/"; D=R+"docs/characters/assets/Starline/"; O=D+"의상/새디자인/"
t=open(R+"docs/characters/도구/옷_다시그림_자르기.py",encoding="utf-8").read()
rows,cols=4,4; exec("def "+t.split("\ndef ",1)[1].split("def mask(c)")[0])
m=json.load(open(D+"의상/전체프레임_v2/칸_목록.json",encoding="utf-8")); SRC={1:6,2:4,3:5,4:2,5:3,6:1}
cs={p:cellsof(cleanup(imread(O+f"전체프레임_{SRC[p]}_다시.png",-1))) for p in SRC}
def big(cell):
    mm=(cell[...,3]>40).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(mm); b=1+int(np.argmax(st[1:,4]))
    cell=cell.copy(); cell[~np.isin(l,[i for i in range(1,n) if st[i,4]>=st[b,4]*0.02])]=0; return cell
out=O+"다시_앱크기/"; stand=imread(out+"stand_0.png",-1); k=stand.shape[0]/_tight(big(cs[1][0])).shape[0]
top=lambda x:x[:int(x.shape[0]*.42)]; r=[]
for x in m:
    if not x["frame"].startswith("motion_tidy"): continue
    f=_tight(big(cs[x["part"]][x["cell"]])); sc=best_scale(top(stand),top(scaled(f,k)),.85,1.15,61); r.append((x["frame"],f,sc))
import statistics
for grp in ("motion_tidy10a","motion_tidy10b"):   # 한 모션 안에서는 같은 배율(장마다 다르면 흔들림)
    md=statistics.median([sc for n,f,sc in r if n.startswith(grp+"_")])
    for n,f,sc in r:
        if n.startswith(grp+"_"): imwrite(out+n+".png",scaled(f,k*md))
    print(grp,"머리 맞춤 배율(공통)",round(md,3))
r=[]
print("서기 키",stand.shape[0],"배율",round(k,3),r)
