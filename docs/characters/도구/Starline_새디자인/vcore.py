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
