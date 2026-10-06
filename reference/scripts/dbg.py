import struct
TPQ=480; BAR=1920; S16=120; S8=240; S4=480

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

def blip(t,note=72,n=3,gap=S8):
    """判定しやすい短い連打"""
    o=[]
    for i in range(n):
        o.append((t+i*gap, non(0,note,110),2))
        o.append((t+i*gap+gap-40, nof(0,note),1))
    return o

# ============ DBG1: プログラムチェンジが届いているか ============
# PC1=12.5% PC2=25% PC3=50% PC4=75% (実装表に明記、マクロ不要)
ev=[]; t=S4
for i,p in enumerate([0,1,2,3]):          # 0-based = PC1..PC4
    ev.append((t-20, pcm(0,p),0))
    ev+=blip(t); t+=BAR
build('/tmp/fmm/dbg1_pc_duty.mid',ev,'DBG1 PC1-4 duty')

# ============ DBG2: CCが届いているか (基準) ============
ev=[]; t=S4
for v in [16,48,80,112]:
    ev.append((t-20, cc(0,70,v),0))
    ev+=blip(t); t+=BAR
build('/tmp/fmm/dbg2_cc70.mid',ev,'DBG2 CC70 duty')

# ============ DBG3: Basicマクロが実行できるか ============
ev=[]; t=S4
ev.append((0, cc(0,49,46),0))             # Basic バンク
for m in range(1,9):
    ev.append((t-20, cc(0,46,m),0))
    ev+=blip(t,n=2); t+=S8*3
build('/tmp/fmm/dbg3_basic_macro.mid',ev,'DBG3 basic macro 1-8')

# ============ DBG4: ユーザーマクロの記録と実行 (PC割当なし) ============
# 記録内容はCC70=16(細い)の1個だけ。その後CC70=80(太い)にしてから実行。
ev=[]; t=S4
ev.append((0,        cc(0,49,47),0))      # User バンク
ev.append((t,        cc(0,45,1),0))       # 記録開始 (macro 1)
ev.append((t+S8*2,   cc(0,70,16),0))      # ← これを記録させたい
ev.append((t+S8*4,   cc(0,45,0),0))       # 記録停止
t+=S8*8
ev.append((t,        cc(0,70,80),0))      # わざと太い音に
ev+=blip(t+S8, n=3); t+=BAR+S8            # 太い音を確認
ev.append((t,        cc(0,47,1),0))       # マクロ1 実行
ev+=blip(t+S8*2, n=3)                     # 細くなれば記録OK
build('/tmp/fmm/dbg4_user_macro.mid',ev,'DBG4 record+exec user macro')

# ============ DBG5: PC割り当て (番号ズレ対策で3通り試す) ============
ev=[]; t=S4
ev.append((0,      cc(0,49,47),0))
ev.append((t,      cc(0,45,2),0))         # macro 2 記録
ev.append((t+S8*2, cc(0,70,16),0))
ev.append((t+S8*4, cc(0,45,0),0))
t+=S8*8
ev.append((t,      cc(0,47,2),0)); t+=S8*3    # 実行
ev.append((t,      cc(0,51,92),0)); t+=S8*6   # PC93 へ割当
# 太い音に戻してから PC92/93/94 を順に試す
for pcv in [91,92,93]:
    ev.append((t, cc(0,70,80),0)); t+=S8
    ev+=blip(t,n=2); t+=S8*3
    ev.append((t, pcm(0,pcv),0)); t+=S8
    ev+=blip(t,n=2); t+=S8*4
build('/tmp/fmm/dbg5_assign_pc.mid',ev,'DBG5 assign to PC then test 91-93')
print('built 5 files')
