import cv2,numpy as np,sys
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread
def hairw(img,top=0.32):
    lab=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2LAB).astype(np.float32); L,A,B=lab[...,0],lab[...,1]-128,lab[...,2]-128
    ang=np.degrees(np.arctan2(B,A)); C=np.hypot(A,B)
    w=np.clip((29-ang)/3+0.5,0,1)*(C<45)                    # 분홍(피부는 더 주황 쪽이라 빠짐)
    w=np.where(C<20,((L>185)&(C>8)&(ang<45)).astype(np.float32),w)   # 옅고 밝은 머리(이·흰자 C<8 제외)
    w*=(A>4)&(img[...,3]>0)&(L>110)
    H=img.shape[0]; ear=np.zeros_like(w); ear[:int(H*top)]=np.clip((C[:int(H*top)]-31)/4,0,1)   # 귀 안쪽 진분홍
    return w*(1-ear)
def ivory2(img,ka=0.25,db=5,dl=2):
    w=cv2.GaussianBlur(hairw(img),(3,3),0)
    lab=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2LAB).astype(np.float32)
    t=lab.copy(); t[...,1]=128+(lab[...,1]-128)*ka; t[...,2]+=db; t[...,0]+=dl
    lab=lab*(1-w[...,None])+t*w[...,None]; o=img.copy(); o[...,:3]=cv2.cvtColor(np.clip(lab,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); return o
if __name__=="__main__":
    O="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인/다시_앱크기/"
    def comp(x): al=x[...,3:]/255; return (x[...,:3]*al+236*(1-al)).astype(np.uint8)
    rows=[]
    for n in ["stand_0","walk_3","sit_2","pet_2","sneeze_5","land_1","motion_hat_magic_3","drag_1"]:
        a=imread(O+n+".png",-1); b=ivory2(a); h=int(a.shape[0]*.6)
        x=np.hstack([comp(a)[:h],comp(b)[:h]]); rows.append(cv2.resize(x,(int(x.shape[1]*200/h),200)))
    W=max(r.shape[1] for r in rows); rows=[np.pad(r,((0,4),(0,W-r.shape[1]+6),(0,0)),constant_values=255) for r in rows]
    cv2.imwrite(sys.argv[1],np.vstack([np.hstack(rows[i:i+2]) for i in range(0,8,2)]))
