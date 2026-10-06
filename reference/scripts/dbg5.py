import struct
TPQ=480; S16=120; S8=240; S4=480; BAR=1920
def vlq(n):
    o=[n&0x7F]; n>>=7
    while n: o.append((n&0x7F)|0x80); n>>=7
    return bytes(reversed(o))
def cc(c,n,v): return bytes([0xB0|c,n,v])
def pcm(c,p):  return bytes([0xC0|c,p])
def non(c,n,v):return bytes([0x90|c,n,v])
def nof(c,n):  return bytes([0x80|c,n,0])
def mk(ev,name,tempo=100):
    d=b''; nb=name.encode('ascii','replace')
    d+=vlq(0)+b'\xFF\x03'+vlq(len(nb))+nb
    d+=vlq(0)+b'\xFF\x51\x03'+(60000000//tempo).to_bytes(3,'big')
    last=0
    for t,m,_ in sorted(ev,key=lambda e:(e[0],e[2])):
        d+=vlq(t-last)+m; last=t
    d+=vlq(0)+b'\xFF\x2F\x00'
    return b'MTrk'+struct.pack('>I',len(d))+d
def build(p,ev,name,tempo=100):
    with open(p,'wb') as f:
        f.write(b'MThd'+struct.pack('>IHHH',6,1,1,TPQ)); f.write(mk(ev,name,tempo))
def hold(t,dur=S4,note=72):
    return [(t,non(0,note,112),2),(t+dur,nof(0,note),1)]

# 完全に無害な埋めCC (すべて電源ON時の既定値と同じ)
PAD=[(85,64),(84,0),(83,0),(89,20),(88,0),(80,0),(81,16),(20,0),
     (21,0),(9,0),(82,2),(11,127),(22,127),(23,0),(30,1)]

# ===== dbg11: 9〜15番目のどこで切れるか =====
ev=[(0,cc(0,49,47),0)]; t=S4
POS=[9,10,11,12,13,14,15]
for i,pos in enumerate(POS):
    m=31+i
    payload=PAD[:pos-1]+[(7,0)]
    ev.append((t, cc(0,45,m),0)); t+=S8*2
    for j,(n,v) in enumerate(payload): ev.append((t+j*60, cc(0,n,v),0))
    t+=len(payload)*60+S8
    ev.append((t, cc(0,45,0),0)); t+=S8*5
    ev.append((t, cc(0,7,127),0)); t+=S8
    ev+=hold(t); t+=S4+S8
    ev.append((t, cc(0,47,m),0)); t+=S8
    ev+=hold(t); t+=S4+S8*2
ev.append((t, cc(0,7,127),0))
build('/tmp/fmm/dbg11_capacity_9to15.mid',ev,'DBG11 mute at pos 9..15')

# ===== 本番v3: 重要な8個だけをマクロに入れる =====
# 効果の大きい順。仮に容量が8でも全部入る
ORD=[70,79,75,72,1,78,73,65]
L1={70:48,79:104,75:16,72:20,1:64,78:46,73:0,65:0}     # 標準
L2={70:80,79:127,75:0, 72:42,1:72,78:54,73:16,65:127}  # バラード
L3={70:16,79:116,75:10,72:14,1:80,78:34,73:0, 65:0}    # サビ
SLOT=[(L1,11,92),(L2,12,93),(L3,13,94)]

ev=[(0,cc(0,49,47),0)]; t=S4
for P,m,pcv in SLOT:
    ev.append((t, cc(0,45,m),0)); t+=S8*2
    for i,num in enumerate(ORD): ev.append((t+i*60, cc(0,num,P[num]),0))
    t+=len(ORD)*60+S8
    ev.append((t, cc(0,45,0),0));   t+=S8*6
    ev.append((t, cc(0,47,m),0));   t+=S8*2
    ev.append((t, cc(0,51,pcv),0)); t+=S8*7
ev.append((t, cc(0,47,11),0)); t+=S8*2
ev.append((t, cc(0,50,1),0))
build('/tmp/fmm/cart_setup_v3.mid',ev,'CART SETUP v3 (8 CC per macro)')

# ===== 共通土台を1回だけ送る (既定値と違うものだけ) =====
ev=[(0,cc(0,77,1),0),(6,cc(0,76,6),0),(12,cc(0,3,0),0),
    (18,cc(0,12,0),0),(24,cc(0,5,4),0),(30,cc(0,82,2),0)]
build('/tmp/fmm/init_common.mid',ev,'INIT common (once after power on)')

# ===== 確認v3 =====
ev=[]; t=S4
for pcv in [92,93,94,92]:
    ev.append((t-20, pcm(0,pcv),0))
    ev+=hold(t,dur=S4*3,note=76); t+=S4*3+S8
    for i,p in enumerate([72,76,79]):
        ev.append((t+i*S16, non(0,p,112),2)); ev.append((t+i*S16+S16-20, nof(0,p),1))
    t+=S4*2
build('/tmp/fmm/cart_verify_v3.mid',ev,'VERIFY v3',112)
print('ORD =',ORD)
for nm,P in [('L1',L1),('L2',L2),('L3',L3)]:
    print(nm, [P[k] for k in ORD])
