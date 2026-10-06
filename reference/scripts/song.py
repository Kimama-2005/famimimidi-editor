import struct
TPQ=480; BAR=1920; S16=120; S32=60; S8=240

def vlq(n):
    o=[n&0x7F]; n>>=7
    while n: o.append((n&0x7F)|0x80); n>>=7
    return bytes(reversed(o))
def cc(c,n,v): return bytes([0xB0|c,n,v])
def non(c,n,v): return bytes([0x90|c,n,v])
def nof(c,n):  return bytes([0x80|c,n,0])
def pb(c,v):
    x=v+8192; return bytes([0xE0|c,x&0x7F,(x>>7)&0x7F])
def mk(ev,name,tempo=None):
    d=b''; nb=name.encode('ascii','replace')
    d+=vlq(0)+b'\xFF\x03'+vlq(len(nb))+nb
    if tempo: d+=vlq(0)+b'\xFF\x51\x03'+(60000000//tempo).to_bytes(3,'big')
    for t,m,_ in sorted(ev,key=lambda e:(e[0],e[2])):
        pass
    last=0
    for t,m,_ in sorted(ev,key=lambda e:(e[0],e[2])):
        d+=vlq(t-last)+m; last=t
    d+=vlq(0)+b'\xFF\x2F\x00'
    return b'MTrk'+struct.pack('>I',len(d))+d
def build(p,tr):
    with open(p,'wb') as f:
        f.write(b'MThd'+struct.pack('>IHHH',6,1,len(tr),TPQ))
        for t in tr: f.write(t)

# ================= PATCH =================
P1=[(121,0),(70,16),(73,0),(75,36),(79,112),(72,10),(12,127),
    (23,127),(24,3),(25,2),(26,4),(27,0),(22,127),
    (76,7),(77,1),(78,34),(80,0),(81,16),(82,12),(85,64),(30,2),(5,4)]
P2=[(121,0),(70,48),(73,0),(75,30),(79,76),(72,8),(12,112),
    (23,127),(24,3),(25,2),(26,5),(22,127),
    (76,7),(77,1),(78,34),(82,12),(85,70),(7,94)]
P3=[(121,0),(73,0),(72,6),(7,127),(82,12),(85,64),(22,127)]
P4=[(121,0),(73,0),(75,10),(79,0),(72,4),(12,127),(17,127),(7,108)]
P5=[(121,0),(18,0),(7,127)]
def patch(c,ps):
    e=[(0,cc(c,ps[0][0],ps[0][1]),0)]
    for i,(n,v) in enumerate(ps[1:],1): e.append((i*3,cc(c,n,v),0))
    e.append((len(ps)*3+6, pb(c,0),0))
    return e

# ================= SONG =================
N=[]
def n(c,t,d,p,v=105): N.append((c,t,d,p,v))
def ch(c,t,d,ps,v=105):
    for x in ps: n(c,t,d,x,v)
def B(b): return b*BAR

E=[52,54,55,57,59,60,62,64,66,67,69,71,72,74,76,78,79,81,83,84,86,88]  # Em scale idx0=E3
EM9=[64,67,71,78]; CM9=[60,64,67,74]; AM7=[57,60,64,67]
B7=[59,63,66,69]; GM=[67,71,74,78]; DM=[62,66,69,72]

# ---- RIFF (bars 0-3) ----
R1=[0,0,3,0,5,0,3,0, 0,0,3,0,7,5,3,0]
R2=[0,0,3,0,5,0,3,0, 0,3,5,7,8,7,5,3]
for b,pat in [(0,R1),(1,R1),(2,R2),(3,R2)]:
    for i,s in enumerate(pat):
        t=B(b)+i*S16
        n(0,t,S16-12,64+s,112)
        n(1,t,S16-12,52+s,88)
        n(2,t,S16-14,40+s,115)
ch(0,B(3)+14*S16,S16*2-20,[71,75,78],118)   # B7 pickup
ch(1,B(3)+14*S16,S16*2-20,[59,63,66],92)
n(2,B(3)+14*S16,S16*2-20,35,118)

# ---- A THEME (bars 4-11) ----
A={4:[(0,2,71),(2,2,74),(4,4,76),(8,2,74),(10,2,71),(12,4,67)],
   5:[(0,2,72),(2,2,76),(4,4,79),(8,4,76),(12,4,72)],
   6:[(0,2,74),(2,2,78),(4,2,79),(6,2,83),(8,6,86),(14,2,83)],
   7:[(0,2,81),(2,2,78),(4,2,74),(6,2,71),(8,8,74)],
   8:[(0,2,71),(2,2,74),(4,2,76),(6,2,79),(8,2,78),(10,2,76),(12,4,71)],
   9:[(0,2,72),(2,2,76),(4,2,79),(6,2,83),(8,2,81),(10,2,79),(12,4,76)],
   10:[(0,2,69),(2,2,72),(4,2,76),(6,2,72),(8,2,69),(10,2,67),(12,4,64)],
   11:[(0,3,71),(3,3,75),(6,3,78),(9,3,81),(12,4,83)]}
for b, evs in A.items():
    for o,d,p in evs:
        t=B(b)+o*S16
        n(0,t,d*S16-10,p,114)
        n(1,t+S16,d*S16-14,p-12,80)

# ---- B THEME (bars 12-19) ----
Bm={12:[(0,6,79),(6,2,78),(8,4,76),(12,4,74)],
    13:[(0,6,78),(6,2,76),(8,4,74),(12,4,69)],
    14:[(0,4,76),(4,2,79),(6,2,83),(8,8,83)],
    15:[(0,4,84),(4,4,83),(8,4,79),(12,4,76)],
    16:[(0,8,86),(8,4,83),(12,4,79)],
    17:[(0,4,81),(4,2,78),(6,2,81),(8,8,86)],
    18:[(0,4,84),(4,4,81),(8,4,76),(12,4,72)],
    19:[(0,4,83),(4,4,81),(8,4,78),(12,2,75),(14,2,71)]}
for b,evs in Bm.items():
    for o,d,p in evs:
        t=B(b)+o*S16
        n(0,t,d*S16-10,p,116)
        n(1,t+S8,max(S16,d*S16-S8-14),p-12,78)

# ---- C SHRED (bars 20-27) ----
RUN={20:[7,9,11,14,11,9,7,9, 11,14,16,18,16,14,11,14, 16,18,21,18,16,14,11,9, 7,9,11,14,16,14,11,9],
     21:[9,11,13,16,13,11,9,11, 13,16,18,20,18,16,13,16, 18,20,21,20,18,16,13,11, 9,11,13,16,18,16,13,11],
     22:[5,7,9,12,9,7,5,7, 9,12,14,16,14,12,9,12, 14,16,19,16,14,12,9,7, 5,7,9,12,14,12,9,7],
     23:[6,8,10,13,10,8,6,8, 10,13,15,17,15,13,10,13, 15,17,20,17,15,13,10,8, 6,8,10,13,15,13,10,8],
     24:[10,12,14,17,14,12,10,12, 14,17,19,21,19,17,14,17, 14,12,10,12,14,17,19,17, 14,12,10,7,5,7,10,12],
     26:[21,20,18,16,14,13,11,9, 7,9,11,13,14,16,18,20, 21,18,16,14,11,9,7,9, 11,14,16,18,21,18,16,14],
     27:[20,18,15,13,10,8,6,8, 10,13,15,18,20,18,15,13, 10,13,15,17,20,17,15,13, 10,8,6,8,10,13,15,17]}
for b,ix in RUN.items():
    for i,k in enumerate(ix):
        t=B(b)+i*S32
        n(0,t,S32-8,E[k],118)
        n(1,t+S32,S32-8,E[k]-12,82)
B7R=[59,63,66,69,71,75,78,81,83,81,78,75,71,69,66,63]*2
for i,p in enumerate(B7R):
    t=B(25)+i*S32
    n(0,t,S32-8,p,118); n(1,t+S32,S32-8,p-12,82)

# ---- D CLIMAX (bars 28-33) ----
CL={28:EM9,29:CM9,30:AM7,31:B7,32:EM9,33:GM}
for b,c_ in CL.items():
    ch(0,B(b),BAR-40,c_,120)
    ch(1,B(b)+S16//2,BAR-60,[x-12 for x in c_[:3]],90)

# ---- TURNAROUND (bars 34-35) ----
DOWN=[21,20,18,16,15,13,11,10,8,6,4,3,1,0]
for i,k in enumerate(DOWN):
    t=B(34)+i*S32
    n(0,t,S32-8,E[k]+12 if E[k]+12<=104 else E[k],118)
    n(1,t+S32,S32-8,E[k],84)
ch(0,B(34)+14*S32,S16*4,[71,75,78,81],120)
ch(1,B(34)+14*S32+S16//2,S16*4-30,[59,63,66],92)
ch(0,B(35)+S16*8,S16*6,[71,75,78,81],122)
ch(1,B(35)+S16*8+S16//2,S16*6-30,[59,63,66],94)

# ---- BASS ch3 (bars 4-35) ----
ROOT={4:40,5:36,6:43,7:38,8:40,9:36,10:33,11:35,
      12:43,13:38,14:40,15:36,16:43,17:38,18:33,19:35,
      20:40,21:43,22:36,23:38,24:33,25:35,26:40,27:38,
      28:40,29:36,30:33,31:35,32:40,33:43,34:35,35:35}
for b in range(4,36):
    r=ROOT[b]
    if 20<=b<=27:
        for i in range(8): n(2,B(b)+i*S8,S8-14,r if i%2==0 else r+12,116)
    elif 28<=b<=33:
        for i in range(16): n(2,B(b)+i*S16,S16-10,r+(12 if i%4==2 else 0),114)
    elif b>=34:
        for i in range(8): n(2,B(b)+i*S8,S8-14,r if i%2==0 else r+12,118)
    else:
        for i,s in enumerate([0,2,3,4,6,7,8,10,11,12,14,15]):
            p=r+12 if i%3==0 else r
            if s==15: p=r+7
            n(2,B(b)+s*S16,S16-12,p,112)

# ---- NOISE ch4 ----
for i in range(16): n(3,B(3)+8*S16+i*S32,S32-6,28-i,60+i*4)   # riser -> A
for i in range(12): n(3,B(19)+10*S16+i*S32,S32-6,26-i*2,70+i*4) # -> C
for i in range(8):  n(3,B(27)+12*S16+i*S32,S32-6,30-i*3,90)     # -> D
for i in range(10): n(3,B(35)+i*S32,S32-6,6+i*2,100-i*5)        # turn

# ---- DRUMS ch5 (DPCM) ----
def dr(b,style='main',fill=False,crash=False):
    t=B(b)
    if style=='half':
        k=[0,8]; s=[4,12]; h=[2,6,10,14]
    elif style=='drive':
        k=[0,3,6,10,13]; s=[4,12]; h=[2,8,14]
    else:
        k=[0,6,10]; s=[4,12]; h=[2,8,14]
    if fill:
        k=[0,6]; s=[4,10,12,13,14,15]; h=[2,8]
    for x in k: n(4,t+x*S16,40,35,120)
    for x in s: n(4,t+x*S16,40,38,114)
    for x in h: n(4,t+x*S16,40,42,88)
    if crash: n(4,t,40,49,120)
for b in range(2,4):  dr(b,'half')
for b in range(4,12): dr(b,'main',fill=(b==11),crash=(b==4))
for b in range(12,20):dr(b,'main',fill=(b==19),crash=(b==12))
for b in range(20,28):dr(b,'drive',fill=(b==27),crash=(b==20))
for b in range(28,34):dr(b,'drive',crash=(b in(28,32)))
dr(34,'drive'); dr(35,'main',fill=True,crash=True)

# ---- pitch bend accents ----
PBE=[]
def dive(c,t,depth,steps=10,span=S16*2):
    for i in range(steps+1):
        PBE.append((t+i*span//steps, pb(c,int(depth*i/steps)),1))
    PBE.append((t+span+20, pb(c,0),1))
dive(0,B(11)+12*S16, 2000, 8, S16*3)
dive(0,B(19)+12*S16,-1500, 8, S16*3)
dive(0,B(33)+8*S16, -6000,12, S16*7)
PBE.append((B(36)-8,pb(0,0),1))

# ================= 出力 =================
def trk(c,ps,name,extra=None,tempo=None,with_patch=True):
    ev=patch(c,ps) if with_patch else []
    off=0
    for cc_,t,d,p,v in N:
        if cc_!=c: continue
        ev.append((t+off,non(c,p,v),2)); ev.append((t+off+d,nof(c,p),1))
    if extra: ev+= [(t+off,m,o) for t,m,o in extra]
    return mk(ev,name,tempo)

names=['Ch1 Lead','Ch2 Echo','Ch3 Tri Bass','Ch4 Noise','Ch5 Drums']
PS=[P1,P2,P3,P4,P5]

# 1) 音色設定のみ
build('/tmp/fmm/follin_patch.mid',
      [mk(patch(i,PS[i]),names[i],152 if i==0 else None) for i in range(5)])
# 2) 曲本体(音符のみ / tick0開始 / シームレスループ)
build('/tmp/fmm/follin_song.mid',
      [trk(0,P1,names[0],extra=PBE,tempo=152,with_patch=False)]+
      [trk(i,PS[i],names[i],with_patch=False) for i in range(1,5)])
# 3) 設定+曲(お手軽版)
build('/tmp/fmm/follin_song_full.mid',
      [trk(0,P1,names[0],extra=PBE,tempo=152)]+
      [trk(i,PS[i],names[i]) for i in range(1,5)])
print('notes',len(N))
