import struct
TPQ=480; BAR=1920; S16=120; S8=240

def vlq(n):
    o=[n&0x7F]; n>>=7
    while n: o.append((n&0x7F)|0x80); n>>=7
    return bytes(reversed(o))
def cc(c,n,v): return bytes([0xB0|c,n,v])
def pcm(c,p):  return bytes([0xC0|c,p])
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

KEYS=[23,21,20,3,9,22,85,82,7,11,
      70,73,12,75,79,72,83,
      1,76,77,78,80,81,
      86,87,88,89,92,
      65,5,84,30]
BASE={23:0,21:0,20:0,3:0,9:0,22:127,85:64,82:2,7:127,11:127,
      77:1,80:0,84:0,30:1,83:0,88:0,89:20}
V1={**BASE,70:48,73:0,12:0,75:16,79:104,72:20,1:64,76:6,78:46,81:16,86:0,87:0,92:0,65:0,5:4}
V2={**BASE,70:80,73:16,12:56,75:0,79:127,72:42,1:72,76:5,78:54,81:12,86:0,87:0,92:0,65:127,5:5}
V3={**BASE,70:16,73:0,12:0,75:10,79:116,72:14,1:80,76:8,78:34,81:16,86:30,87:16,92:12,65:0,5:3}

# マクロ番号 / 割り当て先PC (PC番号 = CC51値 + 1)
SLOT=[('v1',V1,1,92),('v2',V2,2,93),('v3',V3,3,94)]

# ---------- カートリッジ書き込み (1回だけ再生) ----------
ev=[]; t=BAR
ev.append((0, cc(0,49,47), 0))                  # マクロバンク = User
for name,P,m,pcv in SLOT:
    ev.append((t, cc(0,45,m),0)); t+=S8*2        # 記録開始
    for i,num in enumerate(KEYS):
        ev.append((t+i*30, cc(0,num,P[num]),0))
    t+=len(KEYS)*30+S8
    ev.append((t, cc(0,45,0),0));   t+=S8*4      # 記録停止 (書き込み待ち)
    ev.append((t, cc(0,47,m),0));   t+=S8*2      # 実行
    ev.append((t, cc(0,51,pcv),0)); t+=S8*5      # PC へ割り当て (書き込み待ち)
ev.append((t, cc(0,47,1),0)); t+=S8*2            # マクロ1を実行
ev.append((t, cc(0,50,1),0)); t+=S8*5            # 電源ON時のマクロに設定 (ch1)
build('/tmp/fmm/cart_setup_pc93.mid',[mk(ev,'CART WRITE PC93-95 + STARTUP',100)])

# ---------- 動作確認: PC93/94/95 を直接送る ----------
MEL=[(0,4,72),(4,4,76),(8,4,79),(12,4,76)]
ev=[]
for i,pcv in enumerate([92,93,94,92]):
    b=i*2
    ev.append((max(0,b*BAR-20), pcm(0,pcv),0))
    for o,d,p in MEL:
        t=b*BAR+o*S16
        ev.append((t,non(0,p,110),2)); ev.append((t+d*S16-12,nof(0,p),1))
# 伸ばし音の途中で切替
t=8*BAR
ev.append((t,non(0,77,116),2))
for i,pcv in enumerate([93,94,92]):
    ev.append((t+(i+1)*S8*2, pcm(0,pcv),0))
ev.append((t+S8*8,nof(0,77),1))
build('/tmp/fmm/cart_verify_pc93.mid',[mk(ev,'VERIFY PC93-95',132)])

# ---------- マクロが複数chをまたげるか試すテスト ----------
ev=[]; t=S8*2
ev.append((0, cc(0,49,47),0))
ev.append((t, cc(0,45,10),0)); t+=S8*2           # マクロ10 記録開始
ev.append((t, cc(0,70,16),0))                    # ch1 = 細い音
ev.append((t+30, cc(3,7,0),0))                   # ch4 = 消音
t+=S8
ev.append((t, cc(0,45,0),0)); t+=S8*4            # 停止
# わざと別の状態に戻す
ev.append((t, cc(0,70,80),0))                    # ch1 = 太い音
ev.append((t+30, cc(3,7,127),0))                 # ch4 = 音あり
ev.append((t+60, cc(3,75,14),0)); ev.append((t+62, cc(3,79,0),0))
ev.append((t+64, cc(3,12,127),0))
t+=S8*2
def phrase(t0):
    o=[]
    for i,p in enumerate([72,76,79,84]):
        o.append((t0+i*S8, non(0,p,110),2)); o.append((t0+i*S8+S8-20, nof(0,p),1))
    for i in range(8):
        o.append((t0+i*S16, non(3,6,120),2)); o.append((t0+i*S16+40, nof(3,6),1))
    return o
ev+=phrase(t); t+=BAR+S8                          # 変更前を聴く
ev.append((t, cc(0,47,10),0)); t+=S8*2            # マクロ10 実行
ev+=phrase(t)                                      # 変更後を聴く
build('/tmp/fmm/cart_test_multichannel.mid',[mk(ev,'TEST multi-ch macro',110)])
print('built')
