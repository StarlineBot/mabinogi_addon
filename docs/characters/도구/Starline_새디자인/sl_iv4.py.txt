# 털색 아이보리 v4: 색을 영역별로 고르게 펴고(mean shift) 나서 '분홍(머리) vs 주황(피부)' 각도로 가르고, 마스크를 중앙값으로 다듬음
# (v2: 픽셀마다 → 자글자글, v3: 장마다 표본 통계 → 몇 장에서 얼굴·손까지 머리로 잡혀 피부가 회색 — 사용자 11-27)
import cv2,numpy as np
def hairw(img,top=0.32,th=29.5):
    H,W=img.shape[:2]; op=img[...,3]>200
    bgr=np.ascontiguousarray(img[...,:3]); f=cv2.pyrMeanShiftFiltering(bgr,4,14)
    lab=cv2.cvtColor(f,cv2.COLOR_BGR2LAB).astype(np.float32); L,A,B=lab[...,0],lab[...,1]-128,lab[...,2]-128
    C=np.hypot(A,B); ang=np.degrees(np.arctan2(B,A))
    t=th+np.clip((L-190)/10,0,1)*6            # 아주 밝은 곳(L>190)은 피부가 거의 없어 머리 쪽으로 넓게
    w=np.clip((t-ang)/2+0.5,0,1)*(C<48)*(A>4)*(L>110)
    w=np.where((C<20)&(C>8)&(L>185)&(ang<45),1.0,w)
    w=w*op
    w=cv2.medianBlur((w*255).astype(np.uint8),5).astype(np.float32)/255*op
    lab0=cv2.cvtColor(bgr,cv2.COLOR_BGR2LAB).astype(np.float32); C0=np.hypot(lab0[...,1]-128,lab0[...,2]-128)
    ear=np.zeros_like(w); ear[:int(H*top)]=np.clip((C0[:int(H*top)]-31)/4,0,1)
    return w*(1-ear)
def ivory2(img,ka=0.25,db=5,dl=2):
    w=cv2.GaussianBlur(hairw(img),(3,3),0)
    lab=cv2.cvtColor(img[...,:3],cv2.COLOR_BGR2LAB).astype(np.float32)
    t=lab.copy(); t[...,1]=128+(lab[...,1]-128)*ka; t[...,2]+=db; t[...,0]+=dl
    lab=lab*(1-w[...,None])+t*w[...,None]; o=img.copy(); o[...,:3]=cv2.cvtColor(np.clip(lab,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); return o
