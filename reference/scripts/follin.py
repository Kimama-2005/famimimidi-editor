import struct

TPQ=480; BAR=1920; S16=120; S32=60

def vlq(n):
    out=[n & 0x7F]; n>>=7
    while n:
        out.append((n & 0x7F)|0x80); n>>=7
    return bytes(reversed(out))

def cc(ch,num,val): return bytes([0xB0|ch,num,val])
def pc(ch,num):     return bytes([0xC0|ch,num])
def on(ch,note,vel): return bytes([0x90|ch,note,vel])
def off(ch,note):    return bytes([0x80|ch,note,0])
def pb(ch,val):
    v=val+8192; return bytes([0xE0|ch, v & 0x7F, (v>>7)&0x7F])

def mktrack(abs_events, name, tempo=None):
    data=b''
    nb=name.encode('shift_jis','replace')
    data+=vlq(0)+b'\xFF\x03'+vlq(len(nb))+nb
    if tempo:
        us=60000000//tempo
        data+=vlq(0)+b'\xFF\x51\x03'+us.to_bytes(3,'big')
    ev=sorted(abs_events,key=lambda e:(e[0],e[2]))
    last=0
    for t,msg,_ in ev:
        data+=vlq(t-last)+msg; last=t
    data+=vlq(0)+b'\xFF\x2F\x00'
    return b'MTrk'+struct.pack('>I',len(data))+data

def build(path,tracks):
    with open(path,'wb') as f:
        f.write(b'MThd'+struct.pack('>IHHH',6,1,len(tracks),TPQ))
        for t in tracks: f.write(t)

# ============ 音色設定 (Tim Follin style) ============
# ch1: リード / 高速アルペジオ和音
P1=[(121,0),(70,16),(73,0),(75,36),(79,112),(72,10),(12,127),
    (23,127),(24,3),(25,2),(26,4),(27,0),
    (22,127),(76,7),(77,1),(78,30),(80,0),(81,16),
    (82,12),(85,64),(30,2),(5,4),(84,0)]
# ch2: ディレイ/カウンター (少し細く、デチューン)
P2=[(121,0),(70,48),(73,0),(75,30),(79,72),(72,8),(12,112),
    (23,127),(24,3),(25,2),(26,5),
    (22,127),(76,7),(77,1),(78,30),(82,12),(85,70),(7,96)]
# ch3: 三角波ベース
P3=[(121,0),(73,0),(72,6),(7,127),(82,12),(85,64),(22,127)]
# ch4: ノイズ (リフ/アクセント)
P4=[(121,0),(73,0),(75,10),(79,0),(72,4),(12,127),(17,127),(7,110)]
# ch5: DPCM ドラム
P5=[(121,0),(18,0),(7,127)]

def patch(ch,pairs,t0=0):
    e=[(t0,cc(ch,pairs[0][0],pairs[0][1]),0)]
    for i,(n,v) in enumerate(pairs[1:],1):
        e.append((t0+2+i, cc(ch,n,v), 0))
    return e

NOTES=[]
def n(ch,tick,dur,note,vel=100):
    NOTES.append((ch,tick,dur,note,vel))
def chord(ch,tick,dur,notes,vel=100):
    for x in notes: n(ch,tick,dur,x,vel)

def bar(b): return int(b*BAR)

EM=[64,67,71]; C=[60,64,67]; G=[67,71,74]; D=[62,66,69]
AM=[57,60,64]; B7=[59,63,66,69]; EM9=[64,67,71,78]

# ---------- INTRO (bar 0-3) ----------
sc=[52,55,57,59,62,64,67,69,71,74,76,79,81,83,86,88]
for i,p in enumerate(sc):
    n(0,bar(0)+i*S16,S16-8,p,90+i)
desc=[88,86,83,81,79,76,74,71]
for i,p in enumerate(desc):
    n(0,bar(1)+i*S32,S32-4,p,110)
chord(0,bar(1)+8*S32,int(BAR*1.5)-8*S32,EM9,115)
# ノイズ・ライザー
for i in range(16):
    n(3,bar(1)+BAR//2+i*S32, S32-4, 30-i, 70+i*3)
chord(0,bar(2),BAR*2-20,EM9,120)
chord(1,bar(2)+S16,BAR*2-20-S16,[64,67,71],90)
n(4,bar(2),S16,49,110)   # crash

# ---------- A (bar 4-11) ----------
MEL={
 4:[(0,2,71),(2,2,74),(4,4,76),(8,2,74),(10,2,71),(12,4,67)],
 5:[(0,2,72),(2,2,76),(4,4,79),(8,4,76),(12,4,72)],
 6:[(0,2,74),(2,2,78),(4,2,79),(6,2,83),(8,6,86),(14,2,83)],
 7:[(0,2,81),(2,2,78),(4,2,74),(6,2,71),(8,8,74)],
 8:[(0,2,71),(2,2,74),(4,4,76),(8,2,79),(10,2,76),(12,4,74)],
 9:[(0,2,72),(2,2,76),(4,4,79),(8,2,83),(10,2,79),(12,4,76)],
 10:[(0,2,69),(2,2,72),(4,2,76),(6,2,72),(8,2,69),(10,2,67),(12,4,64)],
 11:[(0,4,71),(4,4,75),(8,4,78),(12,4,83)],
}
for b,ev in MEL.items():
    for off_,dur,p in ev:
        t=bar(b)+off_*S16
        n(0,t,dur*S16-10,p,112)
        n(1,t+S16,dur*S16-14,p-12,78)   # オクターブ下のエコー

CH={4:EM,5:C,6:G,7:D,8:EM,9:C,10:AM,11:B7}
BASS={4:40,5:36,6:43,7:38,8:40,9:36,10:33,11:35}
for b in range(4,12):
    r=BASS[b]
    pat=[0,2,3,4,6,7,8,10,11,12,14,15]
    for i,s in enumerate(pat):
        p=r if i%3 else r+12
        if s==14: p=r+7
        n(2,bar(b)+s*S16,S16-10,p,110)

# ---------- B: 高速ラン (bar 12-15) ----------
EMSC=[64,66,67,69,71,72,74,76,78,79,81,83,84,86,88]
RUNS={
 12:[0,2,4,6,4,2,0,2, 4,6,8,10,8,6,4,6, 8,10,12,14,12,10,8,10, 12,10,8,6,4,2,0,2],
 13:[3,5,7,9,7,5,3,5, 7,9,11,13,11,9,7,9, 11,13,14,13,11,9,7,5, 3,5,7,9,11,9,7,5],
 14:[1,3,5,7,5,3,1,3, 5,7,9,11,9,7,5,7, 9,11,13,11,9,7,5,3, 1,3,5,7,9,11,13,14],
 15:[14,12,10,8,10,12,14,12, 10,8,6,4,6,8,10,8, 6,4,2,0,2,4,6,8, 10,12,14,12,10,8,6,4],
}
BCH={12:EM,13:G,14:C,15:D}
for b,idxs in RUNS.items():
    for i,ix in enumerate(idxs):
        t=bar(b)+i*S32
        n(0,t,S32-6,EMSC[ix],115)
        n(1,t+S32,S32-6,EMSC[ix]-12,80)
for b,r in {12:40,13:43,14:36,15:38}.items():
    for i in range(8):
        n(2,bar(b)+i*(S16*2),S16*2-12,r if i%2==0 else r+12,115)

# ---------- B2: 和音クライマックス (bar 16-19) ----------
CL={16:EM9,17:C+[79],18:B7,19:EM9}
for b,ch_ in CL.items():
    chord(0,bar(b),BAR-40,ch_,120)
    chord(1,bar(b)+S16//2,BAR-40,[x-12 for x in ch_[:3]],88)
for b,r in {16:40,17:36,18:35,19:40}.items():
    for i in range(16):
        n(2,bar(b)+i*S16,S16-10,r+(12 if i%4==2 else 0),112)
# ピッチベンド・ダイブ (bar 19後半)
PBEV=[]
for i in range(17):
    PBEV.append((bar(19)+BAR//2+i*60, pb(0,-int(8191*i/16)), 1))
PBEV.append((bar(20)-10, pb(0,0),1))

# ---------- OUTRO (bar 20) ----------
chord(0,bar(20),BAR,EM9,120)
chord(1,bar(20)+S16,BAR-S16,[52,55,59],95)
n(2,bar(20),BAR,40,120)
n(4,bar(20),S16,49,115)
for i in range(12):
    n(3,bar(20)+i*S32,S32-4,4+i*2,100-i*5)

# ---------- ドラム ch5 ----------
def drums(b,fill=False):
    t=bar(b)
    for s in ([0,6,10] if not fill else [0,6,10,13]): n(4,t+s*S16,40,35,120)
    for s in ([4,12] if not fill else [4,12,14,15]): n(4,t+s*S16,40,38,115)
    for s in [2,8,14] if not fill else [2,8]: n(4,t+s*S16,40,42,90)
for b in range(2,21):
    drums(b, fill=(b in (11,15,19)))

# ============ 出力 ============
def trk(ch,pairs,name,extra=None,tempo=None):
    ev=patch(ch,pairs)
    for c,t,d,p,v in NOTES:
        if c!=ch: continue
        ev.append((t+20,on(ch,p,v),2)); ev.append((t+20+d,off(ch,p),1))
    if extra: ev+=extra
    return mktrack(ev,name,tempo)

tracks=[
 trk(0,P1,'Ch1 Lead/Arp',extra=PBEV,tempo=152),
 trk(1,P2,'Ch2 Echo'),
 trk(2,P3,'Ch3 Tri Bass'),
 trk(3,P4,'Ch4 Noise'),
 trk(4,P5,'Ch5 DPCM Drums'),
]
build('/tmp/fmm/follin_demo.mid',tracks)

# 音色設定のみ
psets=[mktrack(patch(i,p),nm,152 if i==0 else None)
       for i,(p,nm) in enumerate([(P1,'Ch1 Lead/Arp'),(P2,'Ch2 Echo'),
            (P3,'Ch3 Tri Bass'),(P4,'Ch4 Noise'),(P5,'Ch5 DPCM Drums')])]
build('/tmp/fmm/follin_patch.mid',psets)
print('bars:',21,'notes:',len(NOTES))
