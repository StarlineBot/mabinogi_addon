# 어깨 털기(motion_tidy10a): 눈 아래쪽 절반의 진한 검은 테두리(아래 눈가)만 지움 — 위 속눈썹은 그대로(사용자 11-27)
import cv2,numpy as np,sys
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite
def fix(a):
    H,W=a.shape[:2]; hsv=cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2HSV).astype(int); op=a[...,3]>200
    iris=(hsv[...,0]>=15)&(hsv[...,0]<=32)&(hsv[...,1]>150)&(hsv[...,2]>150)&op; iris[:int(H*.2)]=0; iris[int(H*.45):]=0
    ys,xs=np.where(iris); cy,cx=int(np.median(ys)),int(np.median(xs))
    box=np.zeros((H,W),bool); box[max(0,cy-16):cy+18,max(0,cx-50):min(W,cx+50)]=True
    white=(hsv[...,2]>200)&(hsv[...,1]<45)&op
    inner=cv2.morphologyEx(((iris|white)&box).astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    n,lab,st,_=cv2.connectedComponentsWithStats(inner); dark=(hsv[...,2]<140)&op&box; m=np.zeros((H,W),bool)
    for i in range(1,n):
        if st[i,4]<25: continue                       # 눈(흰자+눈동자) 덩어리만
        e=(lab==i).astype(np.uint8); y0,h=st[i,1],st[i,3]; mid=y0+int(h*0.45)
        near=cv2.dilate(e,np.ones((7,7),np.uint8))>0; low=np.zeros_like(near); low[mid:]=True
        m|=dark&near&low&(e==0)
    o=a.copy(); o[...,:3]=cv2.inpaint(a[...,:3],cv2.dilate(m.astype(np.uint8),np.ones((2,2),np.uint8))*255,3,cv2.INPAINT_TELEA); return o,int(m.sum())
if __name__=="__main__":
    d=sys.argv[1]
    for i in range(12):
        p=d+f"motion_tidy10a_{i}.png"; o,n=fix(imread(p,-1)); imwrite(sys.argv[2]+f"motion_tidy10a_{i}.png",o); print(i,n,end="  ")
