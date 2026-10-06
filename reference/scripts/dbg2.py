import struct
TPQ=480; S16=120; S8=240; S4=480; BAR=1920
def vlq(n):
    o=[n&0x7F]; n>>=7
    while n: o.append((n&0x7F)|0x80); n>>=7
    return bytes(reversed(o))
def cc(c,n,v): return bytes([0xB0|c,n,v])
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
def blip(t,n=2,note=72,gap=S8):
    o=[]
    for i in range(n):
        o.append((t+i*gap, non(0,note,110),2)); o.append((t+i*gap+gap-40, nof(0,note),1))
    return o

# CC70=16 を必ず含む、長さNのCCリスト
POOL=[(70,16),(79,0),(75,10),(72,4),
      (73,0),(12,127),(1,64),(76,6),
      (78,40),(80,0),(81,16),(22,127),
      (23,0),(21,0),(20,0),(3,0),
      (9,0),(85,64),(82,2),(7,127),
      (11,127),(77,1),(83,0),(86,0),
      (87,0),(88,0),(89,20),(92,0),
      (65,0),(5,4),(84,0),(30,1)]

def rec_and_test(ev,t,macro,ccs,spacing):
    """記録 → 太い音に戻す → 実行 → 判定用の音"""
    ev.append((t, cc(0,45,macro),0)); t+=S8*2
    for i,(n,v) in enumerate(ccs):
        ev.append((t+i*spacing, cc(0,n,v),0))
    t+=len(ccs)*spacing+S8
    ev.append((t, cc(0,45,0),0)); t+=S8*5      # 停止 + 書き込み待ち
    ev.append((t, cc(0,70,80),0)); t+=S8        # わざと太い音
    ev+=blip(t,n=2); t+=S8*3                    # 太いはず
    ev.append((t, cc(0,47,macro),0)); t+=S8     # マクロ実行
    ev+=blip(t,n=2); t+=S8*5                    # 細くなれば成功
    return t

# ---- dbg6: 容量テスト (4 / 8 / 16 個) ----
ev=[(0,cc(0,49,47),0)]; t=S4
for macro,cnt in [(5,4),(6,8),(7,16)]:
    t=rec_and_test(ev,t,macro,POOL[:cnt],30)
build('/tmp/fmm/dbg6_capacity.mid',ev,'DBG6 macro capacity 4-8-16')

# ---- dbg7: 32個を「ゆっくり」記録 (間隔300ms) ----
ev=[(0,cc(0,49,47),0)]; t=S4
t=rec_and_test(ev,t,8,POOL[:32],S8)
build('/tmp/fmm/dbg7_slow32.mid',ev,'DBG7 32CC slow spacing')

# ---- dbg8: 32個を元と同じ速さで (比較用) ----
ev=[(0,cc(0,49,47),0)]; t=S4
t=rec_and_test(ev,t,9,POOL[:32],30)
build('/tmp/fmm/dbg8_fast32.mid',ev,'DBG8 32CC fast spacing')
print('built')
