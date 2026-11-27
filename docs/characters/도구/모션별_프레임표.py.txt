"""모션별 프레임표 — 다시 그릴 동작 하나만 첨부할 수 있게(사용자 11-26).
4명: 전체프레임_v2(앱 크기·머리 맞춤 끝난 칸)를 그룹별로 다시 배치. Starline: 앱 프레임 + 25·75 원본(서 있기 머리 맞춤)."""
import sys, os, json, numpy as np, cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread, imwrite, split, _tight, scaled
from scripts.build_aria_frames import clean
from scripts.silhouette import best_scale
R="/home/user/mabinogi_addon/"; DOC=R+"docs/characters/assets/"; APP=R+"src/mabinogi_addon/assets/characters/"
KO={"stand":"서있기","hair":"머리쓰다듬기","watch":"시계보기","walk":"걷기","stretch":"기지개","surprise":"놀람","drag":"끌기","fall":"떨어지기",
    "land":"착지","getup":"넘어졌다일어나기","pet":"쓰다듬기","magic":"마법연습","crouch":"웅크리기","sit":"구석앉기","sleep":"잠자기","wake":"깨기",
    "rise":"구석에서일어나기","talk":"말하기","flame":"대기불꽃","sneeze":"재채기"}
GRID={"이안":(240,330),"아리아":(249,330),"다래":(310,330),"레나":(310,330)}
def group_of(n):
    if n.startswith("motion:"):
        lab=n.split(":")[1].rsplit("_",1)[0]; nm,st=lab[:-4],lab[-3:-1]; return f"모션{st}_{nm}"
    return KO[n.split("_")[0]]
def cut_v2(ch):
    CW,CH=GRID[ch]; d=DOC+ch+"/의상/전체프레임_v2/"; m=json.load(open(d+"칸_목록.json",encoding="utf-8"))
    sheets={}; out=[]
    for x in m:
        p=x["part"]
        if p not in sheets: sheets[p]=imread(d+f"전체프레임_{p}.png",-1)
        cols=sheets[p].shape[1]//CW; r,c=divmod(x["cell"],cols)
        cell=sheets[p][r*CH+3:(r+1)*CH-3,c*CW+3:(c+1)*CW-3].copy()
        b,g,rr=[cell[...,i].astype(int) for i in range(3)]; cell[(b==255)&(g==170)&(rr==0)]=0  # 칸 선
        out.append((x["frame"],_tight(cell)))
    return out
def starline():
    names=sorted([f[:-4] for f in os.listdir(APP+"Starline") if f.endswith(".png") and not f.startswith(("card","frame"))])
    order=list(KO); names.sort(key=lambda n:(order.index(n.split("_")[0]),n))
    out=[(n,_tight(imread(APP+f"Starline/{n}.png",-1))) for n in names]
    stand=dict(out)["stand_0"]; top=lambda x:x[:int(x.shape[0]*.42)]
    for label,fn in (("장난불꽃(25)","스타 발사 마법사 6컷 애니메이션.png"),("모자마술(75)","토끼 귀 마법사의 모자 소동.png")):
        fs=[_tight(f) for f in split(clean(imread(DOC+"Starline/SD/"+fn,-1))) if f.shape[0]>60]
        k0=stand.shape[0]/np.median([f.shape[0] for f in fs])
        k=k0*float(np.median([best_scale(top(stand),top(scaled(f,k0)),.85,1.15,61) for f in fs]))
        out+=[(f"motion:{label}_{i}",scaled(f,k)) for i,f in enumerate(fs)]
    return out
report={}
for ch in ["이안","아리아","다래","레나","Starline"]:
    frames=cut_v2(ch) if ch!="Starline" else starline()
    if ch=="Starline":
        CW=max(240,max(f.shape[1] for _,f in frames)+16); CH=max(330,max(f.shape[0] for _,f in frames)+16)
    else: CW,CH=GRID[ch]
    groups={}
    for n,f in frames: groups.setdefault(group_of(n),[]).append((n,f))
    od=DOC+ch+"/의상/모션별/"; os.makedirs(od,exist_ok=True); table={}
    for gname,items in groups.items():
        n=len(items); cols=min(4,n) if n!=6 and n!=9 else 3; rows=-(-n//cols)
        can=np.zeros((CH*rows,CW*cols,4),np.uint8)
        for i,(name,f) in enumerate(items):
            r,c=divmod(i,cols); fh,fw=f.shape[:2]; x=c*CW+(CW-fw)//2; y=r*CH+CH-8-fh
            reg=can[y:y+fh,x:x+fw]; a=f[...,3:4]/255.0
            reg[...,:3]=(f[...,:3]*a+reg[...,:3]*(1-a)).astype(np.uint8); reg[...,3]=np.maximum(reg[...,3],f[...,3])
        for r in range(rows):
            for c in range(cols): cv2.rectangle(can,(c*CW+1,r*CH+1),((c+1)*CW-2,(r+1)*CH-2),(255,170,0,255),2)
        imwrite(od+f"{gname}.png",can); table[gname]={"cols":cols,"rows":rows,"cell":[CW,CH],"frames":[nm for nm,_ in items]}
    json.dump(table,open(od+"칸_목록.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
    report[ch]={g:len(v["frames"]) for g,v in table.items()}; print(ch,CW,CH,report[ch])
