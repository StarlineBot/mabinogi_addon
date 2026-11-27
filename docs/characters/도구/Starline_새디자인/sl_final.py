import sys,os,glob,numpy as np,cv2
S=sys.argv[1]; sys.path.insert(0,S); sys.path.insert(0,"/home/user/mabinogi_addon")
from sl_iv4 import ivory2
from scripts.build_dare_frames import imread,imwrite,_tight
R="/home/user/mabinogi_addon/"; D=R+"docs/characters/assets/Starline/"; O=D+"의상/새디자인/"
src=O+"장색맞춤/"; fin=O+"새디자인_앱크기/"; os.makedirs(fin,exist_ok=True)
C=[45,130,210]
def wts(L):
    w=np.stack([np.exp(-((L-c)/40.)**2) for c in C],-1); return w/w.sum(-1,keepdims=True)
def bandstats(a):
    al=a[...,3]>200; lab=cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2LAB).astype(float)[al]; w=wts(lab[:,0])
    mu=np.array([(lab*w[:,i:i+1]).sum(0)/w[:,i].sum() for i in range(3)])
    sd=np.array([np.sqrt(((lab-mu[i])**2*w[:,i:i+1]).sum(0)/w[:,i].sum()) for i in range(3)]); return mu,sd
sh=imread(D+"시안_11-26_아이보리.png",-1); sh=_tight(sh[:,:sh.shape[1]//2])
iv={os.path.basename(f)[:-4]:ivory2(imread(f,-1)) for f in sorted(glob.glob(src+"*.png"))}
mt,st=bandstats(sh); ms,ss=bandstats(iv["stand_0"]); k=np.clip(st/np.maximum(ss,1),0.8,1.25)
def tone(a):
    lab=cv2.cvtColor(a[...,:3],cv2.COLOR_BGR2LAB).astype(float); w=wts(lab[...,0])
    o=sum(w[...,i:i+1]*((lab-ms[i])*k[i]+mt[i]) for i in range(3)); b=a.copy(); b[...,:3]=cv2.cvtColor(np.clip(o,0,255).astype(np.uint8),cv2.COLOR_LAB2BGR); return b
for n,a in iv.items(): imwrite(fin+n+".png",a)   # 톤 맞추기는 피부가 붉어져 뺌(털색만)
print(len(iv),"장")
def comp(x,bg=236): al=x[...,3:]/255; return (x[...,:3]*al+bg*(1-al)).astype(np.uint8)
from PIL import Image,ImageDraw,ImageFont
fs=glob.glob("/usr/share/fonts/**/*CJK*",recursive=True); font=ImageFont.truetype(fs[0],14)
ims=[("새 시안(아이보리)",sh),("받은 그림 그대로",imread(src+"stand_0.png",-1)),("털색만(넘길 것)",iv["stand_0"]),("참고: 시안 톤까지 맞춤",tone(iv["stand_0"])),("지금 앱",imread(R+"src/mabinogi_addon/assets/characters/Starline/stand_0.png",-1))]
H=300; can=Image.new("RGB",(5*220,H+40),(236,236,236)); d=ImageDraw.Draw(can)
for i,(t,x) in enumerate(ims):
    x=cv2.resize(x,(int(x.shape[1]*H/x.shape[0]),H),interpolation=cv2.INTER_AREA); im=Image.fromarray(cv2.cvtColor(x,cv2.COLOR_BGRA2RGBA))
    can.paste(im,(i*220+110-im.size[0]//2,36),im); d.text((i*220+6,8),t,fill=(50,50,50),font=font)
can.save(D+"Starline_새디자인_색비교.png")
# 동작 GIF(앱 속도: 한 장 0.3초=2틱, 사이 모션 0.13초≈1틱, 대기 1초≈7틱, 틱 0.15초)
A=R+"src/mabinogi_addon/assets/characters/Starline/"
def seq(names,t=2,hold={}): return sum([[n]*hold.get(i,t) for i,n in enumerate(names)],[])
M=[("서 있기",seq(["stand_0"],4)),("걷기",seq([f"walk_{i}" for i in range(8)])),("대기 불꽃",seq([f"flame_{i}" for i in range(4)])),
   ("재채기",seq([f"sneeze_{i}" for i in range(6)])),("끌기",seq([f"drag_{i}" for i in range(4)])),("떨어지기·착지",seq(["fall_0","fall_0","land_0","land_1","land_2"])),
   ("쓰다듬기",seq([f"pet_{i}" for i in range(6)])),("웅크리기·구석",seq(["crouch_0","crouch_1"]+[f"sit_{i}" for i in range(4)]+["rise_0","rise_1"])),
   ("말하기",seq(["talk_base_0","talk_m1_0","talk_m2_0","talk_mid_0","talk_blink_0","talk_emph_0","talk_emph2_0","talk_end1_0","talk_end2_0"])),
   ("25 장난 불꽃",seq([f"motion_flame_shot_{i}" for i in range(6)],hold={0:7})),("75 모자 마술",seq([f"motion_hat_magic_{i}" for i in range(6)],hold={1:7})),
   ("10 어깨·금장",seq([f"motion_tidy10a_{i}" for i in range(12)],1)),("10 소매·팔찌",seq([f"motion_tidy10b_{i}" for i in range(12)],1))]
fr={n:Image.fromarray(cv2.cvtColor(imread(fin+n+".png",-1),cv2.COLOR_BGRA2RGBA)) for n in iv}
T=max(len(s) for _,s in M)+4; cw,chh=210,330; out=[]
for t in range(T):
    can=Image.new("RGB",(5*cw,3*chh),(236,236,236)); d=ImageDraw.Draw(can)
    for j,(lab,s) in enumerate(M):
        r,c=divmod(j,5); n=s[min(t,len(s)-1)] if t<len(s)+2 else s[-1]; n=s[t%len(s)] if lab in("걷기","서 있기") else (s[t] if t<len(s) else s[-1])
        im=fr[n]; can.paste(im,(c*cw+cw//2-im.size[0]//2,r*chh+chh-8-im.size[1]),im); d.text((c*cw+6,r*chh+6),lab,fill=(50,50,50),font=font)
    out.append(can)
def gif_frames(frames):
    # 모든 장이 같은 256색 팔레트를 쓰고 점찍기(디더링) 없이 — 장마다 팔레트가 바뀌면 머리 색이 장마다 달라져 자글자글해 보임(사용자 11-27)
    W,H=frames[0].size; mont=Image.new("RGB",(W,H*len(frames)))
    for i,f in enumerate(frames): mont.paste(f,(0,H*i))
    pal=mont.quantize(colors=256,method=Image.Quantize.MEDIANCUT)
    return [f.quantize(palette=pal,dither=Image.Dither.NONE) for f in frames]
out=gif_frames(out)
g=D+"Starline_새디자인_전체동작.gif"; out[0].save(g,save_all=True,append_images=out[1:],duration=150,loop=0,optimize=True); print(g,T,"틱")
