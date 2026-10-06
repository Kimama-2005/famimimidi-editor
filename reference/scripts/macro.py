import struct
TPQ=480; BAR=1920; S16=120; S8=240

def vlq(n):
    o=[n&0x7F]; n>>=7
    while n: o.append((n&0x7F)|0x80); n>>=7
    return bytes(reversed(o))
def cc(c,n,v): return bytes([0xB0|c,n,v])
def pcm(c,p):  return bytes([0xC0|c,p])       # p = 0-based
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

# ============================================================
# 全パッチが「同じCC番号を全部」指定する = リセット不要
# CC121 を含めないのがシームレス化の要点
# ============================================================
KEYS=[23,21,20,3,9,22,85,82,7,11,
      70,73,12,75,79,72,83,
      1,76,77,78,80,81,
      86,87,88,89,92,
      65,5,84,30]
BASE={23:0,21:0,20:0,3:0,9:0,22:127,85:64,82:2,7:127,11:127,
      77:1,80:0,84:0,30:1,83:0,88:0,89:20}
V1={**BASE,70:48,73:0,12:0,75:16,79:104,72:20,
    1:64,76:6,78:46,81:16, 86:0,87:0,92:0, 65:0,5:4}
V2={**BASE,70:80,73:16,12:56,75:0,79:127,72:42,
    1:72,76:5,78:54,81:12, 86:0,87:0,92:0, 65:127,5:5}
V3={**BASE,70:16,73:0,12:0,75:10,79:116,72:14,
    1:80,76:8,78:34,81:16, 86:30,87:16,92:12, 65:0,5:3}
PATCH={'v1':V1,'v2':V2,'v3':V3}
MACRO={'v1':1,'v2':2,'v3':3}           # ユーザーマクロ番号
PCNUM={'v1':88,'v2':89,'v3':90}        # 0-based → PC89 / PC90 / PC91

# ---------- 1) マクロ記録 & PC割り当て (1回だけ再生) ----------
ev=[]; t=BAR                                    # 1小節の余白から開始
ev.append((0,cc(0,49,47),0))                    # マクロバンクを User に
for k in ('v1','v2','v3'):
    m=MACRO[k]; P=PATCH[k]
    ev.append((t, cc(0,45,m),0)); t+=S8*2        # 記録開始
    for i,num in enumerate(KEYS):
        ev.append((t+i*30, cc(0,num,P[num]),0))
    t+=len(KEYS)*30+S8
    ev.append((t, cc(0,45,0),0));  t+=S8*3       # 記録停止 (保存待ち)
    ev.append((t, cc(0,47,m),0));  t+=S8*2       # 実行 = "最後に実行したマクロ"
    ev.append((t, cc(0,51,PCNUM[k]),0)); t+=S8*4 # PC へ割り当て (保存待ち)
build('/tmp/fmm/jpop_macro_setup.mid',[mk(ev,'MACRO SETUP (play once)',100)])

# ---------- 2) リセット不要インライン・パッチ (DAWに貼る用) ----------
for k,P in PATCH.items():
    e=[(i*4, cc(0,num,P[num]),0) for i,num in enumerate(KEYS)]
    build(f'/tmp/fmm/inline_to_{k}.mid',[mk(e,f'INLINE {k.upper()} (no reset)',132)])

# ---------- 3) 差分のみ (最小レイテンシ) ----------
import itertools
DIFFS={}
for a,b in itertools.permutations(PATCH,2):
    d=[n for n in KEYS if PATCH[a][n]!=PATCH[b][n]]
    DIFFS[(a,b)]=d
    e=[(i*4, cc(0,n,PATCH[b][n]),0) for i,n in enumerate(d)]
    build(f'/tmp/fmm/diff_{a}_to_{b}.mid',[mk(e,f'DIFF {a}->{b}',132)])

# ---------- 4) PC切替デモ (伴奏なし / 4小節ごとに音色が変わる) ----------
MEL={0:[(2,2,72,96),(4,2,74,98),(6,2,76,100),(8,6,77,112),(14,2,76,96)],
     1:[(0,4,79,112),(4,2,77,100),(6,2,76,98),(8,4,74,100),(12,4,72,96)],
     2:[(0,2,71,98),(2,2,72,100),(4,4,74,106),(8,4,76,108),(12,4,71,96)],
     3:[(0,6,72,106),(6,2,74,100),(8,8,69,104)]}
ev=[]
order=['v1','v2','v3','v1']
for blk,k in enumerate(order):
    b0=blk*4
    # 小節線の 20tick 前に PC を1個だけ置く (= 約0.6ms)
    ev.append((max(0,b0*BAR-20), pcm(0,PCNUM[k]),0))
    for bb in range(4):
        for o,d,p,v in MEL[bb]:
            t=(b0+bb)*BAR+o*S16
            ev.append((t,non(0,p,v),2)); ev.append((t+d*S16-12,nof(0,p),1))
# 伸ばした音の途中で切り替わることを確認する区間
t=16*BAR
ev.append((t,non(0,77,116),2))
for i,k in enumerate(['v2','v3','v1']):
    ev.append((t+(i+1)*S8*2, pcm(0,PCNUM[k]),0))
ev.append((t+S8*8,nof(0,77),1))
ev.insert(0,(0,pbm(0,0),0))
for i,num in enumerate(KEYS):   # 先頭だけ初期化
    ev.insert(0,(i*4, cc(0,num,V1[num]),0))
build('/tmp/fmm/jpop_pc_switch_demo.mid',[mk(ev,'PC SWITCH DEMO',132)])

print('CC count per full patch:',len(KEYS))
for (a,b),d in DIFFS.items(): print(f'{a}->{b}: {len(d)} CC  {d}')
