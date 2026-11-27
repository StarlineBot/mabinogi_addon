import sys,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread,imwrite,_tight,scaled
R="/home/user/mabinogi_addon/"; O=R+"docs/characters/assets/Starline/의상/새디자인2/새걷기/"
t=open(R+"docs/characters/도구/옷_다시그림_자르기.py",encoding="utf-8").read(); rows,cols=4,4
exec("def "+t.split("\ndef ",1)[1].split("def mask(c)")[0])
def big(cell):
    mm=(cell[...,3]>40).astype(np.uint8); n,l,st,_=cv2.connectedComponentsWithStats(mm); b=1+int(np.argmax(st[1:,4]))
    cell=cell.copy(); cell[~np.isin(l,[i for i in range(1,n) if st[i,4]>=st[b,4]*0.02])]=0; return _tight(cell)
import os; out=O+"앱크기/"; os.makedirs(out,exist_ok=True)
st=big(cleanup(imread(O+"서있기_주머니.png",-1))); APPH=282
imwrite(out+"stand_pocket.png",scaled(st,APPH/st.shape[0]))
w=cleanup(imread(O+"걷기_12장.png",-1)); xs=[(83,287),(445,640),(803,1005),(1165,1370)]; ys=[(14,337),(375,699),(738,1061)]
fr=[big(w[y0:y1,x0:x1]) for (y0,y1) in ys for (x0,x1) in xs]
k=APPH/fr[0].shape[0]    # 0번(정면 서기)을 앱 서 있기 키에 맞춤 — 시트 전체 같은 배율
for i,f in enumerate(fr): imwrite(out+f"walk12_{i}.png",scaled(f,k))
print("서기 원본 키",st.shape[0],"걷기 0번 키",fr[0].shape[0],"배율",round(k,3),"앱 키",[round(f.shape[0]*k) for f in fr])

# 왼쪽 걷기 12장(사용자 11-27)
wl=cleanup(imread(O+"왼쪽걷기_12장.png",-1)); xs=[(104,312),(435,676),(790,1022),(1156,1359)]; ys=[(7,352),(370,708),(732,1073)]
frl=[big(wl[y0:y1,x0:x1]) for (y0,y1) in ys for (x0,x1) in xs]
kl=APPH/frl[0].shape[0]
for i,f in enumerate(frl): imwrite(out+f"walkL12_{i}.png",scaled(f,kl))
print("왼쪽 걷기 0번 키",frl[0].shape[0],"배율",round(kl,3),"앱 키",[round(f.shape[0]*kl) for f in frl])
