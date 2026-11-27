import sys,os,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite,_tight,scaled
O="/home/user/mabinogi_addon/docs/characters/assets/Starline/의상/새디자인2/제미나이걷기/"
a=imread(O+"키잉.png",-1); xs=[(35,220),(339,492),(623,779),(897,1085)]; ys=[(24,276),(313,565),(601,852)]
def big(c):
    mm=(c[...,3]>40).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(mm); b=1+int(np.argmax(st[1:,4]))
    c=c.copy(); c[~np.isin(l,[i for i in range(1,n) if st[i,4]>=st[b,4]*0.02])]=0; return _tight(c)
fr=[big(a[y0-20:y1+12,max(0,x0-30):x1+30]) for (y0,y1) in ys for (x0,x1) in xs]
hs=[f.shape[0] for f in fr]; print("원본 키",hs)
# 새 걷기(새디자인2/새걷기) 옆모습 키 중앙값 283에 맞춤(시트 같은 배율)
k=283/float(np.median(hs)); out=O+"앱크기/"; os.makedirs(out,exist_ok=True)
for i,f in enumerate(fr): imwrite(out+f"gwalk_{i}.png",scaled(f,k))
print("배율",round(k,3),"앱 키",[round(h*k) for h in hs])
