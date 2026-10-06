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

# 音に影響しない無害なCC (既定値と同じ)
DUMMY=[(85,64),(84,0),(83,0),(89,20),(88,0),(80,0),(77,1),(81,16),
       (20,0),(21,0),(3,0),(9,0),(82,2),(11,127),(22,127),(23,0),
       (30,1),(76,6),(78,46),(86,0),(87,0),(92,0),(65,0),(5,4),
       (73,0),(12,0),(75,16),(79,104),(72,20),(1,64),(70,48)]

# ===== dbg10: CC7=0 を N 番目に置いて、どこまで記録されるか =====
ev=[(0,cc(0,49,47),0)]; t=S4
POSITIONS=[2,3,4,8,16,32]
for idx,pos in enumerate(POSITIONS):
    m=21+idx
    payload=DUMMY[:pos-1]+[(7,0)]          # pos番目が CC7=0
    ev.append((t, cc(0,45,m),0)); t+=S8*2
    for i,(n,v) in enumerate(payload): ev.append((t+i*60, cc(0,n,v),0))
    t+=len(payload)*60+S8
    ev.append((t, cc(0,45,0),0)); t+=S8*5
    ev.append((t, cc(0,7,127),0)); t+=S8
    ev+=hold(t); t+=S4+S8                   # 鳴る
    ev.append((t, cc(0,47,m),0)); t+=S8    # マクロ実行
    ev+=hold(t); t+=S4+S8*2                 # 無音なら pos番目まで記録できている
ev.append((t, cc(0,7,127),0))
build('/tmp/fmm/dbg10_capacity_pos.mid',ev,'DBG10 mute at pos 2,3,4,8,16,32')
print('dbg10 blocks:',POSITIONS)

# ===== 工場プリセット試聴: 小節番号 = PC番号 =====
ev=[]
for pc in range(1,89):                      # PC1..PC88
    b=pc-1
    t=b*BAR
    ev.append((max(0,t-20), pcm(0,pc-1),0)) # 0-based
    ev+=hold(t, dur=S4*2, note=76)
    for i,p in enumerate([72,79]):
        ev.append((t+S4*2+S8+i*S16, non(0,p,112),2))
        ev.append((t+S4*2+S8+i*S16+S16-20, nof(0,p),1))
build('/tmp/fmm/browse_factory_pc1-88.mid',ev,'BROWSE PC1-88 (bar no = PC no)',120)
