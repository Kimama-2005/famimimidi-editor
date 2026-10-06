import struct

def vlq(n):
    out=[n & 0x7F]; n>>=7
    while n:
        out.append((n & 0x7F)|0x80); n>>=7
    return bytes(reversed(out))

def track(events, name):
    data=b''
    # track name meta
    nb=name.encode('shift_jis')
    data+=vlq(0)+b'\xFF\x03'+vlq(len(nb))+nb
    for delta,msg in events:
        data+=vlq(delta)+msg
    data+=vlq(0)+b'\xFF\x2F\x00'
    return b'MTrk'+struct.pack('>I',len(data))+data

def cc(ch,num,val):
    return bytes([0xB0|ch,num,val])

def build(path, tracks):
    hdr=b'MThd'+struct.pack('>IHHH',6,1,len(tracks),480)
    with open(path,'wb') as f:
        f.write(hdr)
        for t in tracks: f.write(t)

# --- A: 歪みリード / パワーコード (ch1) ---
A=[(70,16),(73,0),(75,70),(79,96),(72,12),
   (23,127),(24,4),(25,3),(26,4),
   (86,24),(87,24),(88,0),(92,18),
   (78,40),(76,6),(77,1),(30,2)]

# --- B: クリーン / アルペジオ (ch1) ---
B=[(70,48),(73,2),(75,45),(79,32),(72,30),
   (23,127),(24,26),(25,20),(26,0),(27,1),
   (65,127),(5,6),(84,40),(85,66)]

def ev(ch, pairs):
    e=[(0,cc(ch,121,0))]          # リセット
    e.append((240,cc(ch,pairs[0][0],pairs[0][1])))  # 少し間をあける
    for num,val in pairs[1:]:
        e.append((0,cc(ch,num,val)))
    return e

# 単体ファイル
build('/tmp/fmm/guitar_A_drive.mid',   [track(ev(0,A),'Guitar A Drive ch1')])
build('/tmp/fmm/guitar_B_clean.mid',   [track(ev(0,B),'Guitar B Clean ch1')])

# ダブリング版: ch1 = A, ch2 = A + Detune70
A2=[p for p in A]+[(85,70)]
build('/tmp/fmm/guitar_A_double.mid',
      [track(ev(0,A),'Guitar A ch1'), track(ev(1,A2),'Guitar A ch2 +detune')])
print("ok")
