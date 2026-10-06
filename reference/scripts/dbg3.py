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

# 判定が二択になるペイロード: CC7=0 で必ず無音になる
MUTE=[(7,0)]+[(23,0),(21,0),(20,0),(3,0),(9,0),(22,127),(85,64),(82,2),(11,127),
      (70,48),(73,0),(12,0),(75,16),(79,104),(72,20),(83,0),
      (1,64),(76,6),(77,1),(78,46),(80,0),(81,16),
      (86,0),(87,0),(88,0),(89,20),(92,0),(65,0),(5,4),(84,0),(30,1)]
assert len(MUTE)==32

# ===== dbg9: マクロ実行 と PC割り当て を別々に判定 =====
ev=[(0,cc(0,49,47),0)]
t=S4
ev.append((t, cc(0,45,11),0)); t+=S8*2
for i,(n,v) in enumerate(MUTE): ev.append((t+i*60, cc(0,n,v),0))
t+=len(MUTE)*60+S8
ev.append((t, cc(0,45,0),0)); t+=S8*6           # 記録停止 + 保存待ち
ev.append((t, cc(0,47,11),0)); t+=S8*2          # 実行 (= 最後に実行したマクロ)
ev.append((t, cc(0,51,92),0)); t+=S8*6          # PC93 へ割り当て + 保存待ち

ev.append((t, cc(0,7,127),0)); t+=S8            # 音量を戻す
ev+=hold(t); t+=S4+S8                            # (A) 鳴る
ev.append((t, cc(0,47,11),0)); t+=S8            # マクロを直接実行
ev+=hold(t); t+=S4+S8                            # (B) 無音なら記録OK
ev.append((t, cc(0,7,127),0)); t+=S8
ev+=hold(t); t+=S4+S8                            # (C) 鳴る
ev.append((t, pcm(0,92),0)); t+=S8              # PC93 を送信
ev+=hold(t); t+=S4+S8                            # (D) 無音なら PC割当もOK
ev.append((t, cc(0,7,127),0))                    # 後始末: 音量を戻す
build('/tmp/fmm/dbg9_mute_test.mid',ev,'DBG9 A:on B:macro C:on D:PC93')

# ===== 本番: 3リードをマクロ11-13 -> PC93/94/95 =====
KEYS=[23,21,20,3,9,22,85,82,7,11,70,73,12,75,79,72,83,
      1,76,77,78,80,81,86,87,88,89,92,65,5,84,30]
BASE={23:0,21:0,20:0,3:0,9:0,22:127,85:64,82:2,7:127,11:127,
      77:1,80:0,84:0,30:1,83:0,88:0,89:20}
V1={**BASE,70:48,73:0,12:0,75:16,79:104,72:20,1:64,76:6,78:46,81:16,86:0,87:0,92:0,65:0,5:4}
V2={**BASE,70:80,73:16,12:56,75:0,79:127,72:42,1:72,76:5,78:54,81:12,86:0,87:0,92:0,65:127,5:5}
V3={**BASE,70:16,73:0,12:0,75:10,79:116,72:14,1:80,76:8,78:34,81:16,86:30,87:16,92:12,65:0,5:3}
SLOT=[(V1,11,92),(V2,12,93),(V3,13,94)]

ev=[(0,cc(0,49,47),0)]; t=S4
for P,m,pcv in SLOT:
    ev.append((t, cc(0,45,m),0)); t+=S8*2
    for i,num in enumerate(KEYS): ev.append((t+i*60, cc(0,num,P[num]),0))
    t+=len(KEYS)*60+S8
    ev.append((t, cc(0,45,0),0));   t+=S8*6
    ev.append((t, cc(0,47,m),0));   t+=S8*2
    ev.append((t, cc(0,51,pcv),0)); t+=S8*7
ev.append((t, cc(0,47,11),0)); t+=S8*2
ev.append((t, cc(0,50,1),0))                    # 電源ON時のマクロ
build('/tmp/fmm/cart_setup_v2.mid',ev,'CART SETUP v2 (macro11-13 -> PC93-95)')

# ===== 確認: 長い音で違いが出るように =====
ev=[]; t=S4
for pcv,lbl in [(92,'V1'),(93,'V2'),(94,'V3'),(92,'V1')]:
    ev.append((t-20, pcm(0,pcv),0))
    ev+=hold(t,dur=S4*3,note=76)       # 長い音 (ビブラートの遅れが分かる)
    t+=S4*3+S8
    for i,p in enumerate([72,76,79]):  # 短い音 (アタックが分かる)
        ev.append((t+i*S16, non(0,p,112),2)); ev.append((t+i*S16+S16-20, nof(0,p),1))
    t+=S4*2
build('/tmp/fmm/cart_verify_v2.mid',ev,'VERIFY v2 long+short notes',112)
print('built')
