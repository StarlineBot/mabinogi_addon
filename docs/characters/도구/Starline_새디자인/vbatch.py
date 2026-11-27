# Starline 영상 동작 일괄: 초록 빼기 → 측정 → 앱 크기(동작마다 같은 틀, 서기 기준 배율) 
import sys,os,glob,json,shutil,numpy as np,cv2
from PIL import Image
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imwrite,scaled
V="/home/user/mabinogi_addon/docs/characters/assets/Starline/영상/"; OUT=V+"앱크기/"
def key(img):
    f=img.astype(np.float32); b,g,r=f[...,0],f[...,1],f[...,2]
    al=np.clip(1-((g-np.maximum(r,b))-25)/70,0,1)
    m=(al>0.5).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(m)
    bi=1+int(np.argmax(st[1:,4])); keep=np.isin(l,[i for i in range(1,n) if st[i,4]>=st[bi,4]*0.02])
    al=al*cv2.dilate(keep.astype(np.uint8),np.ones((3,3),np.uint8))
    g2=np.minimum(g,np.maximum(r,b)+8); return np.dstack([b,g2,r,al*255]).clip(0,255).astype(np.uint8)
def load(p):
    g=Image.open(p); fr=[]
    for i in range(g.n_frames): g.seek(i); fr.append(key(cv2.cvtColor(np.asarray(g.convert("RGB")),cv2.COLOR_RGB2BGR)))
    return fr
def lab_st(fs):
    px=np.concatenate([cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2LAB).astype(float)[a[...,3]>200] for a in fs]); L=px[:,0]
    return np.array([px[(L>=lo)&(L<hi)].mean(0) for lo,hi in [(0,90),(90,190),(190,256)]])
ST=load(V+"0_서있기.gif"); ref_tone=lab_st(ST[::3]); al0=ST[0][...,3]>128; ys0=np.where(al0.any(1))[0]; H0=ys0.max()-ys0.min()
# 머리 폭(위 25%)로 크기 비교
def headw(a):
    m=a[...,3]>128; ys=np.where(m.any(1))[0]; t,b=ys.min(),ys.max(); band=m[t+int((b-t)*.30):t+int((b-t)*.38)]; xs=np.where(band.any(0))[0]; return xs.max()-xs.min()
HW0=headw(ST[0]); K=282/H0
M=[("1_대기불꽃",0),("2_재채기",0),("3_쓰다듬기",0),("4_장난불꽃",0),("5_모자마술",0),("6_어깨금장",0),("7_소매팔찌",0),
   ("8_웅크리기_구석앉기",0),("9_일어나기",-1),("10_끌기",0),("11_떨어지기착지",-1),("12_말하기",0),("13_대기_웃음",0),("14_대기_턱괴기",0)]
rep={}
for name,refi in M:
    F=load(V+name+".gif"); N=len(F); R=F[refi]
    # 영상마다 확대가 다를 수 있음 → 기준 장(서 있는 장) 머리 폭으로 서기 영상에 맞춤
    s=HW0/headw(R); k=K*s
    t=lab_st(F[::3]); de=np.linalg.norm(t-ref_tone,axis=1)
    g0=cv2.cvtColor(ST[0][...,:3],cv2.COLOR_BGR2GRAY).astype(float)
    def sim(a):   # 서기 0번과 겹침(같은 배율로 맞춘 뒤 발 기준)
        b=scaled(a,s); m1=ST[0][...,3]>128; h,w=m1.shape
        c=np.zeros((h,w),bool); bm=b[...,3]>128; ys,xs=np.where(bm)
        if len(ys)==0: return 0
        by,bx=ys.max(),int(xs.mean()); ys2,xs2=np.where(m1); ay,ax=ys2.max(),int(xs2.mean())
        yy=ys-by+ay; xx=xs-bx+ax; ok=(yy>=0)&(yy<h)&(xx>=0)&(xx<w); c[yy[ok],xx[ok]]=True
        return (c&m1).sum()/(c|m1).sum()
    edge=[i for i,a in enumerate(F) if (a[...,3][0:2]>128).any() or (a[...,3][:,0:2]>128).any() or (a[...,3][:,-2:]>128).any()]
    U=np.any([a[...,3]>20 for a in F],axis=0); yy,xx=np.where(U); box=(yy.min(),yy.max()+1,xx.min(),xx.max()+1)
    d=OUT+name+"/"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
    for i,a in enumerate(F): imwrite(d+f"{i:02d}.png",scaled(a[box[0]:box[1],box[2]:box[3]],k))
    rep[name]=dict(배율보정=round(s,3),톤ΔE=[round(x,1) for x in de],시작겹침=round(sim(F[0]),2),끝겹침=round(sim(F[-1]),2),잘린장=edge,틀=list(scaled(F[0][box[0]:box[1],box[2]:box[3]],k).shape[:2]))
    print(name,rep[name])
json.dump(rep,open(OUT+"측정.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
