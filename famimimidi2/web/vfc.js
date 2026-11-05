// 🎮 仮想ファミコン: ふぁみみみっでぃが無くても試せるように、このパソコンで鳴らす音源(WebAudio)。
// Python の出力ポート(device/virtual.py)へ送ったメッセージが vfcFeed() に届く。音は「なんとなく似ている」程度で、
// 実装表の値どおりにデューティ比・エンベロープ・音量・ビブラート・トレモロ・ポルタメント・ピッチベンド・
// ノイズ・DPCM(ドラムはそれっぽい合成音)・波形メモリ・アルペジエーターを効かせる。
// 各 ch は単音(Mode4)。スイープ・ブレス・アフタータッチ・各マクロ(CC#52〜59)はまねしない。
'use strict';

const VFC = {
  ctx: null, node: null, defaults: {}, chans: [], wave: null, on: false,
  GAIN: [0.11, 0.11, 0.17, 0.09, 0.16],              // ch1〜5 の大きさのつり合い
};
const NOISE_PERIODS = [4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068];
const TRI = Array.from({ length: 32 }, (_, i) => (i < 16 ? 15 - i : i - 16));
const DUTY = [0.125, 0.25, 0.5, 0.75];
const CPU = 1789773;

/** 実装表の「指数的。127で約 max 秒」(CC#5 は 12 ≒ 100ms・127 ≒ 5秒 になる曲がり方) */
function timeExp(v, max) { return v <= 0 ? 0 : max * (Math.exp(0.022 * v) - 1) / (Math.exp(0.022 * 127) - 1); }
const steps16 = (v) => Math.floor(v / 8);           // 0-127 を16等分(0〜15)
const enum3 = (v) => (v < 3 ? v : Math.min(2, Math.floor((v - 3) * 3 / 125)));
const enum8 = (v) => (v < 8 ? v : Math.min(7, Math.floor((v - 8) * 8 / 120)));
const deadAmount = (v, dz) => Math.max(0, (v - dz) / Math.max(1, 127 - dz));

class VfcChan {
  constructor(n) { this.n = n; this.reset(); }
  reset() {
    this.cc = Object.assign({}, VFC.defaults);
    this.notes = []; this.note = null; this.vel = 100; this.stage = 'off'; this.env = 0; this.relFrom = 0;
    this.phase = 0; this.pitch = null; this.bend = 0; this.t = 0; this.lfo = 0; this.trem = 0; this.rnd = 0;
    this.lfsr = 1; this.nph = 0; this.pedalHeld = false; this.pendingOff = false;
    this.arpI = 0; this.arpT = 0; this.drum = null; this.hp = 0; this.hpIn = 0;
  }
  get kind() { return this.n === 3 ? 'tri' : this.n === 4 ? 'noise' : this.n === 5 ? (this.cc[18] >= 64 ? 'wave' : 'dpcm') : 'pulse'; }
  arpOn() { return enum3(this.cc[23]) === 2 && this.notes.length >= 2; }
  start() { this.stage = 'attack'; this.env = this.kind === 'tri' ? 1 : steps16(this.cc[12]) / 15; this.t = 0; }
  noteOn(note, vel) {
    if (this.kind === 'dpcm') { this.drum = { note, vel, t: 0 }; return; }
    this.notes = this.notes.filter((x) => x !== note);
    this.notes.push(note);
    this.vel = this.cc[9] >= 8 ? this.cc[9] : vel;
    this.note = note;
    if (this.pitch === null || this.cc[65] < 64 || this.stage === 'off') this.pitch = note;
    this.pendingOff = false;
    this.arpT = 0; this.arpI = 0;
    this.start();
  }
  noteOff(note) {
    if (this.kind === 'dpcm') return;
    this.notes = this.notes.filter((x) => x !== note);
    if (note !== this.note && !this.arpOn()) return;
    if (this.notes.length && (this.cc[22] >= 64 || this.arpOn())) { this.note = this.notes[this.notes.length - 1]; return; }
    if (this.notes.length) return;
    if (this.pedalHeld) { this.pendingOff = true; return; }
    this.release();
  }
  release() { if (this.stage !== 'off') { this.stage = 'release'; this.relFrom = this.env; } }
  stopNow() { this.stage = 'off'; this.env = 0; this.notes = []; this.note = null; this.drum = null; }
  control(cc, v) {
    if (cc === 120) { this.stopNow(); return; }
    if (cc === 123) { this.notes = []; if (this.kind === 'tri') this.stopNow(); else this.release(); return; }
    if (cc === 121) { const keep = this.notes; this.reset(); this.notes = keep; return; }
    this.cc[cc] = v;
    if (cc === 64) {
      this.pedalHeld = v >= 64;
      if (!this.pedalHeld && this.pendingOff && !this.notes.length) { this.pendingOff = false; this.release(); }
    }
  }

  /** 1サンプル分。→ -1〜1 くらいの値 */
  sample(dt) {
    const k = this.kind;
    if (k === 'dpcm') return this.drumSample(dt);
    if (this.stage === 'off') return 0;
    const c = this.cc;
    this.t += dt;
    // アルペジエーター(2ノート以上): 押している音を低い順に、CC#24 の間隔で。CC#25 の長さだけ鳴らす
    if (this.arpOn()) {
      const step = Math.max(1, c[24]) * 0.0079, gate = Math.max(1, Math.min(c[25], c[24])) * 0.0079;
      this.arpT += dt;
      if (this.arpT >= step) {
        this.arpT -= step;
        const order = [...this.notes].sort((a, b) => a - b);
        this.arpI = (this.arpI + 1) % order.length;
        this.note = order[this.arpI]; this.pitch = this.note; this.start();
      } else if (this.arpT >= gate && this.stage !== 'release') this.release();
    }
    // エンベロープ
    const sus = k === 'tri' ? 1 : steps16(c[79]) / 15;
    if (this.stage === 'attack') {
      const at = timeExp(c[73], 10);
      if (at <= 0) this.env = 1; else this.env += dt / at;
      if (this.env >= 1) { this.env = 1; this.stage = 'decay'; }
    } else if (this.stage === 'decay') {
      const de = timeExp(c[75], 10);
      if (de <= 0 || this.env <= sus) { this.env = sus; this.stage = 'sustain'; } else this.env = Math.max(sus, this.env - (1 - sus) * dt / de);
    } else if (this.stage === 'release') {
      const re = timeExp(c[72], 10);
      if (re <= 0) this.env = 0; else this.env -= this.relFrom * dt / re;
      if (this.env <= 0) { this.env = 0; this.stage = 'off'; return 0; }
    }
    // 音の高さ: ポルタメント・ピッチベンド・デチューン・ビブラート
    const target = this.note;
    if (this.pitch !== target) {
      const pt = timeExp(c[5], 5);
      if (c[65] < 64 || pt <= 0) this.pitch = target;
      else { const d = target - this.pitch, s = Math.sign(d) * Math.min(Math.abs(d), Math.max(0.05, Math.abs(d)) * dt / (pt / 3)); this.pitch += s; }
    }
    let semis = this.pitch + this.bend * (c[82] || 2) + (c[85] - 64) / 100;
    if (k !== 'noise') {
      const amt = deadAmount(c[1], c[81]);
      if (amt > 0 && this.t >= timeExp(c[78], 10)) {
        this.lfo = (this.lfo + c[76] * dt) % 1;
        semis += amt * c[77] * lfoShape(enum8(c[80]), this.lfo, this);
      }
    }
    // 大きさ: ボリューム × エクスプレッション × ベロシティ × エンベロープ × トレモロ
    let vol = (c[7] / 127) * (c[11] / 127) * this.env;
    if (k === 'pulse' || k === 'noise') vol *= (Math.floor(this.vel / 8) + 1) / 16;
    else if (k === 'wave') vol *= (Math.floor(this.vel / 4) + 1) / 32;
    if (k !== 'tri' && k !== 'wave') {
      const ta = deadAmount(c[92], c[89]);
      if (ta > 0) { this.trem = (this.trem + c[86] * 0.25 * dt) % 1; vol *= 1 - ta * (steps16(c[87]) / 15) * (0.5 + 0.5 * Math.sin(2 * Math.PI * this.trem)); }
    }
    if (k === 'pulse' || k === 'noise') vol = Math.round(vol * 15) / 15;  // ファミコンらしく16段階
    // 波形
    if (k === 'noise') {
      const idx = c[17] >= 64 ? 15 - (target % 16) : target % 16;
      const rate = CPU / NOISE_PERIODS[idx], short = target >= 64;
      this.nph += rate * dt;
      while (this.nph >= 1) {
        this.nph -= 1;
        const fb = (this.lfsr ^ (this.lfsr >> (short ? 6 : 1))) & 1;
        this.lfsr = (this.lfsr >> 1) | (fb << 14);
      }
      return ((this.lfsr & 1) ? -1 : 1) * vol;
    }
    const f = 440 * Math.pow(2, (semis - 69) / 12);
    this.phase = (this.phase + f * dt) % 1;
    if (k === 'pulse') return (this.phase < DUTY[Math.min(3, Math.floor(c[70] / 32))] ? 1 : -1) * vol;
    if (k === 'tri') return (TRI[Math.floor(this.phase * 32) % 32] / 7.5 - 1) * vol;
    const w = VFC.wave || [8, 10, 12, 14, 15, 14, 12, 10, 8, 6, 4, 2, 0, 2, 4, 6];
    return (w[Math.floor(this.phase * 16) % 16] / 7.5 - 1) * vol;
  }

  /** DPCM: ドラムはそれっぽい合成音(音量 CC#7 は効かない = 実機と同じ) */
  drumSample(dt) {
    const d = this.drum;
    if (!d) return 0;
    d.t += dt;
    const t = d.t, n = d.note, noise = Math.random() * 2 - 1;
    const hi = () => { const y = noise - this.hpIn + 0.6 * this.hp; this.hpIn = noise; this.hp = y; return y; };
    const env = (tau, len) => { if (t > len) { this.drum = null; return 0; } return Math.exp(-t / tau); };
    const sweep = (f0, f1, tau) => { d.ph = ((d.ph || 0) + (f1 + (f0 - f1) * Math.exp(-t / tau)) * dt) % 1; return Math.sin(2 * Math.PI * d.ph); };
    if (n <= 29) return noise * env(0.002, n === 0 ? 0.0064 : 0.002 - (n - 1) * 0.00005 + 0.003) * 0.8;
    switch (n) {
      case 35: case 36: return sweep(160, 45, 0.04) * env(0.18, 0.5);
      case 37: case 39: return (noise * 0.5 + sweep(900, 600, 0.01) * 0.5) * env(0.015, 0.08);
      case 38: case 40: return (noise * 0.7 + sweep(240, 180, 0.03) * 0.4) * env(0.1, 0.35);
      case 41: case 43: case 45: case 47: case 48: case 50: {
        const base = { 41: 85, 43: 105, 45: 125, 47: 150, 48: 175, 50: 205 }[n];
        return sweep(base * 1.5, base, 0.08) * env(0.2, 0.6);
      }
      case 42: case 44: return hi() * env(0.035, 0.15) * 0.8;
      case 46: return hi() * env(0.25, 0.8) * 0.7;
      case 49: return hi() * env(0.7, 2.0) * 0.6;
      case 51: return (hi() * 0.5 + sweep(3200, 3000, 1) * 0.15) * env(0.5, 1.6);
      default: this.drum = null; return 0;
    }
  }
}

function lfoShape(kind, p, ch) {
  switch (kind) {
    case 1: return 2 * p - 1;                         // Saw
    case 2: return 1 - 2 * p;                         // RevSaw
    case 3: return p < 0.25 ? 1 : -1;                 // Pulse25%
    case 4: return p < 0.5 ? 1 : -1;                  // Pulse50%
    case 5: return p < 0.5 ? 4 * p - 1 : 3 - 4 * p;   // Triangle
    case 6: if (p < 0.02) ch.rnd = Math.random() * 2 - 1; return ch.rnd;   // Random
    default: return Math.sin(2 * Math.PI * p);        // SineWave
  }
}

/** Python から届いたメッセージの列([status, d1, d2] か {wave: [16]}) */
window.vfcFeed = (items) => {
  if (!VFC.chans.length) return;
  for (const m of items) {
    if (!Array.isArray(m)) { if (m.wave) VFC.wave = m.wave; continue; }
    const st = m[0], kind = st & 0xF0, ch0 = st & 0x0F;
    if (ch0 >= 15) continue;
    const c = VFC.chans[ch0 % 5];                     // ch のずれ(6〜10・11〜15)にも合わせる
    if (kind === 0x90 && m[2] > 0) c.noteOn(m[1], m[2]);
    else if (kind === 0x80 || kind === 0x90) c.noteOff(m[1]);
    else if (kind === 0xB0) c.control(m[1], m[2]);
    else if (kind === 0xE0) c.bend = (((m[2] << 7) | m[1]) - 8192) / 8192;
  }
};

async function vfcStart() {
  if (!VFC.ctx) {
    VFC.defaults = {};
    const d = await api.vfc_defaults();
    for (const [k, v] of Object.entries(d)) VFC.defaults[+k] = +v;
    VFC.chans = [1, 2, 3, 4, 5].map((n) => new VfcChan(n));
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const node = ctx.createScriptProcessor(1024, 0, 1);
    const dt = 1 / ctx.sampleRate;
    let dc = 0;
    node.onaudioprocess = (e) => {
      const out = e.outputBuffer.getChannelData(0);
      for (let i = 0; i < out.length; i++) {
        let s = 0;
        for (let k = 0; k < 5; k++) s += VFC.chans[k].sample(dt) * VFC.GAIN[k];
        dc += (s - dc) * 0.0005;                          // 直流を取る(低い音のこもりを防ぐ)
        out[i] = Math.max(-1, Math.min(1, s - dc));
      }
    };
    node.connect(ctx.destination);
    VFC.ctx = ctx; VFC.node = node;
  }
  if (VFC.ctx.state !== 'running') await VFC.ctx.resume();
  VFC.on = true;
}

function vfcStop() {
  VFC.on = false;
  VFC.chans.forEach((c) => c.stopNow());
  if (VFC.ctx && VFC.ctx.state === 'running') VFC.ctx.suspend();
}

/** つながり方が変わった(renderStatus から): 仮想ファミコンなら鳴らす。押す前に音が出せないときはクリックを待つ */
window.vfcSync = (conn) => {
  $('btnVfc').classList.toggle('on', !!conn.virtual);
  if (conn.virtual && !VFC.on) {
    vfcStart().then(() => {
      if (VFC.ctx.state !== 'running') {
        toast('仮想ファミコン: 画面のどこかを押すと音が出るようになります');
        window.addEventListener('pointerdown', () => VFC.ctx.resume(), { once: true });
      }
    });
  } else if (!conn.virtual && VFC.on) vfcStop();
};

window.addEventListener('pywebviewready', () => {
  $('btnVfc').onclick = async () => {
    if (!(S.state && S.state.connection.virtual)) await vfcStart();   // 押したときに音を出せるようにしておく
    const r = await api.toggle_virtual();
    if (r && !r.ok && r.message) toast(r.message, 'danger');
    else if (r && r.message) toast(r.message);
    take(r.state);
    if (r.state.connection.virtual) toast('仮想ファミコンで鳴らします(このパソコンの音)。カートリッジへの書き込みと実機の確認はできません');
  };
});
