import sys,os,glob,numpy as np,cv2
sys.path.insert(0,"/home/user/mabinogi_addon")
from scripts.build_dare_frames import imread
from PIL import Image,ImageDraw,ImageFont
R="/home/user/mabinogi_addon/"; D=R+"docs/characters/assets/Starline/"; fin=D+"의상/새디자인3/앱크기/"
fs=glob.glob("/usr/share/fonts/**/*CJK*",recursive=True); font=ImageFont.truetype(fs[0],14)
iv={os.path.basename(f)[:-4]:None for f in glob.glob(fin+"*.png")}
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
g=D+"Starline_새디자인3_전체동작.gif"; out[0].save(g,save_all=True,append_images=out[1:],duration=150,loop=0,optimize=True); print(g,T,"틱")
