import struct
TPQ=480; S16=120; S8=240; S4=480
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

# ============ 校正: 無音マクロを PC89〜128 の全40枠に割り当て ============
ev=[(0,cc(0,49,47),0)]; t=S4
ev.append((t, cc(0,45,20),0)); t+=S8*2        # マクロ20 = 無音
for i,(n,v) in enumerate([(7,0),(11,0)]):
    ev.append((t+i*60, cc(0,n,v),0))
t+=S8*2
ev.append((t, cc(0,45,0),0)); t+=S8*6
ev.append((t, cc(0,47,20),0)); t+=S8*3        # 実行 (= last executed)
for pcv in range(88,128):                      # PC89..PC128 全部に割当
    ev.append((t, cc(0,51,pcv),0)); t+=S8*2
ev.append((t, cc(0,7,127),0)); ev.append((t+8, cc(0,11,127),0))
build('/tmp/fmm/cal_mute_all_userpc.mid',ev,'CAL: mute -> PC89..128')

# ============ 参考: PC1〜40を弾いて現在位置を耳で探る ============
ev=[]; t=S4
for pcv in range(0,40):
    ev.append((t-20, pcm(0,pcv),0))
    ev+=hold(t,dur=S8,note=76); t+=S8*2
build('/tmp/fmm/cal_sweep_pc1-40.mid',ev,'CAL sweep PC1-40')

# ============ 本番 v4: 容量10個いっぱい使う ============
ORD=[70,79,75,72,1,78,73,65,12,92]
L1={70:48,79:104,75:16,72:20,1:64,78:46,73:0, 65:0,  12:0, 92:0}
L2={70:80,79:127,75:0, 72:42,1:72,78:54,73:16,65:127,12:56,92:0}
L3={70:16,79:116,75:10,72:14,1:80,78:34,73:0, 65:0,  12:0, 92:12}
ev=[(0,cc(0,49,47),0)]; t=S4
for P,m,pcv in [(L1,11,92),(L2,12,93),(L3,13,94)]:
    ev.append((t, cc(0,45,m),0)); t+=S8*2
    for i,num in enumerate(ORD): ev.append((t+i*60, cc(0,num,P[num]),0))
    t+=len(ORD)*60+S8
    ev.append((t, cc(0,45,0),0));   t+=S8*6
    ev.append((t, cc(0,47,m),0));   t+=S8*2
    ev.append((t, cc(0,51,pcv),0)); t+=S8*7
ev.append((t, cc(0,47,11),0)); t+=S8*2
ev.append((t, cc(0,50,1),0))
build('/tmp/fmm/cart_setup_v4.mid',ev,'CART SETUP v4 (10 CC per macro)')
print('v4 ORD:',ORD)
for nm,P in [('L1',L1),('L2',L2),('L3',L3)]: print(nm,[P[k] for k in ORD])
