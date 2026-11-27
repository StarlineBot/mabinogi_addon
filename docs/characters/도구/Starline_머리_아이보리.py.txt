import sys,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite,_tight
def hairmask(img):
    hsv=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2HSV).astype(int); H_,S_,V_=hsv[...,0],hsv[...,1],hsv[...,2]
    m=(img[...,3]>0)&(V_>150)&(S_>=18)&(S_<108)&((H_<22)|(H_>160))
    # 토끼귀 안쪽 분홍은 그대로: 귀가 있는 위쪽(키의 24%까지)에서 분홍 기운 강한 곳(Lab a ≥148) 제외
    a=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2LAB)[...,1].astype(int); H=img.shape[0]
    inner=np.zeros_like(m); inner[:int(H*0.24)]=a[:int(H*0.24)]>=148
    inner=cv2.morphologyEx(inner.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))>0
    return m&~inner
def ivory(img,ka=0.25,db=5,dl=2):
    m=hairmask(img); w=cv2.GaussianBlur(m.astype(np.float32),(3,3),0)
    lab=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2LAB).astype(np.float32)
    tgt=lab.copy(); tgt[...,1]=128+(lab[...,1]-128)*ka; tgt[...,2]=lab[...,2]+db; tgt[...,0]=lab[...,0]+dl
    lab=lab*(1-w[...,None])+tgt*w[...,None]
    o=img.copy(); o[...,:3]=cv2.cvtColor(np.clip(lab,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); return o
S=sys.argv[1]
sheet=imread("docs/characters/assets/Starline/시안_11-26.png",-1); ref=_tight(sheet[:, :sheet.shape[1]//2])
vs=[ref,ivory(ref,0.25,5,2),ivory(ref,0.15,9,3)]
def comp(x): al=x[...,3:]/255; return (x[...,:3]*al+236*(1-al)).astype(np.uint8)
full=np.hstack([np.pad(comp(v),((0,0),(0,10),(0,0)),constant_values=255) for v in vs])
H=ref.shape[0]; head=np.hstack([np.pad(comp(v)[0:int(H*.42)],((0,0),(0,10),(0,0)),constant_values=255) for v in vs])
head=cv2.resize(head,None,fx=full.shape[1]/head.shape[1],fy=full.shape[1]/head.shape[1])
for i,t in enumerate(["now","ivory","ivory cream (warmer)"]): cv2.putText(full,t,(i*(ref.shape[1]+10)+8,24),0,.8,(60,60,60),2)
cv2.imwrite(S+"ivory2.png",cv2.resize(np.vstack([full,np.full((8,full.shape[1],3),255,np.uint8),head]),None,fx=.75,fy=.75))
imwrite(S+"sl_sian_ivory.png",vs[1]); imwrite(S+"sl_sian_cream.png",vs[2])
