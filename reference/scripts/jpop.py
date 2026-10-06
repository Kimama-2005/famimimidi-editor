import struct
TPQ=480; BAR=1920; S16=120; S32=60; S8=240

def vlq(n):
    o=[n&0x7F]; n>>=7
    while n: o.append((n&0x7F)|0x80); n>>=7
    return bytes(reversed(o))
def cc(c,n,v): return bytes([0xB0|c,n,v])
def non(c,n,v):return bytes([0x90|c,n,v])
def nof(c,n):  return bytes([0x80|c,n,0])
def pbm(c,v):
    x=max(0,min(16383,v+8192)); return bytes([0xE0|c,x&0x7F,(x>>7)&0x7F])
def mk(ev,name,tempo=None):
    d=b''; nb=name.encode('ascii','replace')
    d+=vlq(0)+b'\xFF\x03'+vlq(len(nb))+nb
    if tempo: d+=vlq(0)+b'\xFF\x51\x03'+(60000000//tempo).to_bytes(3,'big')
    last=0
    for t,m,_ in sorted(ev,key=lambda e:(e[0],e[2])):
        d+=vlq(t-last)+m; last=t
    d+=vlq(0)+b'\xFF\x2F\x00'
    return b'MTrk'+struct.pack('>I',len(d))+d
def build(p,tr):
    with open(p,'wb') as f:
        f.write(b'MThd'+struct.pack('>IHHH',6,1,len(tr),TPQ))
        for t in tr: f.write(t)
def patch(c,ps,pb0=True):
    e=[(0,cc(c,ps[0][0],ps[0][1]),0)]
    for i,(n,v) in enumerate(ps[1:],1): e.append((i*3,cc(c,n,v),0))
    if pb0: e.append((len(ps)*3+6,pbm(c,0),0))
    return e

# ============================================================
#  JPOP CHIPTUNE LEAD  —  3 variants  (すべて ch1 / 完全単音)
# ============================================================
COMMON=[(121,0),(23,0),(21,0),(20,0),(3,0),(9,0),(22,127),(85,64),(82,2),(7,127),(11,127)]

# V1 標準リード: 25% duty / 遅れビブラート / 軽いピッキング感
V1=COMMON+[(70,48),(73,0),(12,0),(75,16),(79,104),(72,20),(83,0),
           (1,64),(76,6),(77,1),(78,46),(80,0),(81,16),
           (86,0),(87,0),(92,0),(65,0),(5,4),(30,1)]
# V2 バラード/甘め: 50% duty / 深く遅いビブラート / 柔らかい立ち上がり
V2=COMMON+[(70,80),(73,16),(12,56),(75,0),(79,127),(72,42),(83,0),
           (1,72),(76,5),(77,1),(78,54),(80,0),(81,12),
           (86,0),(87,0),(92,0),(65,127),(5,5),(84,0),(30,1)]
# V3 サビ/抜け重視: 12.5% duty / 速いビブラート + 薄いトレモロ
V3=COMMON+[(70,16),(73,0),(12,0),(75,10),(79,116),(72,14),(83,0),
           (1,80),(76,8),(77,1),(78,34),(80,0),(81,16),
           (86,30),(87,16),(88,0),(89,20),(92,12),(65,0),(5,3),(30,1)]
VAR={'v1_standard':V1,'v2_ballad':V2,'v3_chorus':V3}

# 伴奏パッチ (デモ用・リードを邪魔しない)
PB2=[(121,0),(70,16),(73,0),(12,0),(75,10),(79,24),(72,6),(23,0),(22,0),(7,74)]
PB3=[(121,0),(73,0),(72,8),(7,120),(22,127),(23,0),(85,64)]
PB4=[(121,0),(73,0),(75,12),(79,0),(72,3),(12,127),(17,127),(7,116),(22,0),(23,0)]

# ============================================================
#  DEMO: 王道進行 (F-G-Em-Am) / C major / 132BPM / 16bars
# ============================================================
N=[]
def n(c,t,d,p,v=105): N.append((c,t,d,p,v))
def B(b): return b*BAR

MEL={
 0:[(2,2,72,96),(4,2,74,98),(6,2,76,100),(8,6,77,112),(14,2,76,96)],
 1:[(0,4,79,112),(4,2,77,100),(6,2,76,98),(8,4,74,100),(12,4,72,96)],
 2:[(0,2,71,98),(2,2,72,100),(4,4,74,106),(8,4,76,108),(12,4,71,96)],
 3:[(0,6,72,106),(6,2,74,100),(8,8,69,104)],
 4:[(2,2,72,98),(4,2,74,100),(6,2,76,104),(8,6,77,114),(14,2,79,102)],
 5:[(0,4,81,116),(4,2,79,104),(6,2,77,100),(8,8,76,106)],
 6:[(0,2,76,100),(2,2,77,102),(4,4,79,110),(8,4,81,112),(12,4,79,102)],
 7:[(0,6,77,108),(6,2,76,100),(8,8,74,104)],
 8:[(0,4,84,122),(4,2,83,110),(6,2,81,108),(8,6,79,114),(14,2,81,104)],
 9:[(0,4,83,118),(4,4,81,110),(8,8,79,112)],
 10:[(0,2,79,104),(2,2,81,108),(4,4,83,116),(8,4,84,118),(12,4,83,108)],
 11:[(0,6,81,114),(6,2,79,106),(8,8,76,108)],
 12:[(0,4,77,110),(4,2,79,108),(6,2,81,112),(8,6,84,120),(14,2,86,116)],
 13:[(0,8,86,122),(8,4,84,114),(12,4,83,110)],
 14:[(0,4,81,112),(4,4,79,108),(8,4,77,104),(12,4,76,100)],
 15:[(0,14,72,110)],
}
for b,evs in MEL.items():
    for o,d,p,v in evs: n(0,B(b)+o*S16,d*S16-12,p,v)

# しゃくり (フレーズ頭を半音下から)
PBE=[]
for b in (0,4,8,12):
    t=B(b)+(2*S16 if b in(0,4) else 0)
    for i in range(7):
        PBE.append((t-70+i*12, pbm(0,int(-4000*(1-i/6))),1))
    PBE.append((t+20,pbm(0,0),1))
PBE.append((B(16)-20,pbm(0,0),1))

CHD={0:[65,69,72],1:[67,71,74],2:[64,67,71],3:[69,72,76],
     4:[65,69,72],5:[67,71,74],6:[64,67,71],7:[67,71,74],
     8:[65,69,72],9:[67,71,74],10:[64,67,71],11:[69,72,76],
     12:[65,69,72],13:[67,71,74],14:[69,72,76],15:[60,64,67]}
ROOT={0:41,1:43,2:40,3:45,4:41,5:43,6:40,7:43,
      8:41,9:43,10:40,11:45,12:41,13:43,14:45,15:36}
for b in range(16):
    a=CHD[b]; seq=[a[0],a[1],a[2],a[1]]*4
    for i,p in enumerate(seq):
        n(1,B(b)+i*S16,S16-14,p,86 if i%4==0 else 74)
    r=ROOT[b]
    for i,s in enumerate([0,2,4,6,7,8,10,12,14,15]):
        n(2,B(b)+s*S16,S16-12,r+(12 if s in(4,12) else 0),112)

KICK,SNARE,HAT,OHAT,CRASH=15,6,1,0,0
DEC={KICK:20,SNARE:14,HAT:5,OHAT:34,CRASH:56}
DV ={KICK:127,SNARE:112,HAT:62,OHAT:78,CRASH:124}
DD ={KICK:70,SNARE:70,HAT:40,OHAT:150,CRASH:260}
DCC=[]
def hit(t,i,v=None):
    DCC.append((max(0,t-12),cc(3,75,DEC[i]),0))
    n(3,t,DD[i],i,v or DV[i])
for b in range(16):
    t=B(b); fill=(b in(7,15))
    k=[0,6,10] if not fill else [0,4,6,10]
    s=[4,12]   if not fill else [8,12,13,14,15]
    h=[2,8,14] if not fill else [2]
    if b in(0,8): k=[x for x in k if x]; hit(t,CRASH)
    for x in k: hit(t+x*S16,KICK)
    for x in s: hit(t+x*S16,SNARE)
    for x in h: hit(t+(x)*S16, OHAT if x==14 and b%4==3 else HAT)

def trk(c,ps,name,extra=None,tempo=None,wp=True):
    ev=patch(c,ps) if wp else []
    for cc_,t,d,p,v in N:
        if cc_!=c: continue
        ev.append((t,non(c,p,v),2)); ev.append((t+d,nof(c,p),1))
    if extra: ev+=list(extra)
    return mk(ev,name,tempo)

for key,V in VAR.items():
    # 音色設定のみ (ch1)
    build(f'/tmp/fmm/jpop_lead_{key}_patch.mid',[mk(patch(0,V),'Ch1 JPOP Lead',132)])
    # デモ (リード + 伴奏)
    build(f'/tmp/fmm/jpop_lead_{key}_demo.mid',
          [trk(0,V,'Ch1 Lead',extra=PBE,tempo=132),
           trk(1,PB2,'Ch2 Backing Arp'),
           trk(2,PB3,'Ch3 Tri Bass'),
           trk(3,PB4,'Ch4 Noise Drums',extra=DCC)])
    # ソロ確認用 (リードのみ)
    build(f'/tmp/fmm/jpop_lead_{key}_solo.mid',
          [trk(0,V,'Ch1 Lead',extra=PBE,tempo=132)])
print('ok',len(N))
