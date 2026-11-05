// 演奏する場所(「♪ 演奏セット」タブ)のうち、割り当て表(色の帯)・ひな形・ペダル・レバー(SPEC_v2 5.3.5・5.4・7.2)。
// 値の正しさ(範囲・ポリの自動紐付け・送り先の既定値)は Python が決める。ここは見せ方と操作だけ。
'use strict';

const KB = { LO: 36, HI: 96 };        // 帯の下の鍵盤は C2〜C7
const TPL_PICS = {
  ch1: ['var(--c1)'],
  poly: ['linear-gradient(var(--c1) 50%,var(--c2) 50%)'],
  unison: ['repeating-linear-gradient(90deg,var(--c1) 0 4px,var(--c2) 4px 8px)'],
  bass_melody: ['var(--c3)', 'var(--c1)'],
  bass_poly: ['var(--c3)', 'linear-gradient(var(--c1) 50%,var(--c2) 50%)'],
  bass_unison: ['var(--c3)', 'repeating-linear-gradient(90deg,var(--c1) 0 4px,var(--c2) 4px 8px)'],
};
const pl = { kb: null, built: false, drag: null };
const kbWhites = [];
for (let n = KB.LO; n <= KB.HI; n++) if (![1, 3, 6, 8, 10].includes(n % 12)) kbWhites.push(n);

/** 鍵 n の左端の位置(%)。黒鍵は左の白鍵の右寄り */
function kpos(n) {
  if (n <= KB.LO) return 0;
  if (n > KB.HI) return 100;
  const i = kbWhites.findIndex((w) => w >= n);
  const black = [1, 3, 6, 8, 10].includes(n % 12);
  return ((i - (black ? 0.32 : 0)) / kbWhites.length) * 100;
}
function kend(n) {           // 鍵 n の右端
  if (n >= KB.HI) return 100;
  return kpos(n + 1);
}
/** 位置(%)→ 一番近い鍵 */
function noteAtPct(p) {
  let best = KB.LO, bd = 1e9;
  for (let n = KB.LO; n <= KB.HI; n++) {
    const c = (kpos(n) + kend(n)) / 2, d = Math.abs(c - p);
    if (d < bd) { bd = d; best = n; }
  }
  return best;
}
const nn = (n) => `${['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][n % 12]}${Math.floor(n / 12) - 1}`;

function buildMiniKb() {
  const el = $('minikb');
  const W = 100 / kbWhites.length;
  let html = '';
  kbWhites.forEach((n) => { html += `<div class="w">${n % 12 === 0 ? `<span>C${Math.floor(n / 12) - 1}</span>` : ''}</div>`; });
  for (let n = KB.LO; n <= KB.HI; n++) {
    if (![1, 3, 6, 8, 10].includes(n % 12)) continue;
    const i = kbWhites.indexOf(n - 1);
    html += `<div class="b" style="left:${(i + 1) * W - W * 0.32}%;width:${W * 0.64}%"></div>`;
  }
  el.innerHTML = html;
}

/** app.js の applyState から呼ばれる */
window.renderPlay = (st) => {
  if (!pl.built) { buildMiniKb(); buildStatic(); pl.built = true; }
  if (pl.drag) return;                    // 帯を動かしている最中は上書きしない
  const s = st.session;
  pl.kb = JSON.parse(JSON.stringify(s.keyboard));
  drawBands();
  document.querySelectorAll('#pairPick .opt').forEach((o) => o.classList.toggle('on', o.dataset.pair === pl.kb.pair));
  drawControls(s.controls);
};

function buildStatic() {
  $('tpls').innerHTML = S.state.session.templates.map(([k, name]) =>
    `<div class="tpl" data-tpl="${k}"><div class="pic">${(TPL_PICS[k] || []).map((b) => `<i style="background:${b}"></i>`).join('')}</div>${esc(name)}</div>`).join('');
  $('tpls').onclick = async (e) => {
    const t = e.target.closest('[data-tpl]');
    if (!t) return;
    take(await api.apply_template(t.dataset.tpl));
    toast(`ひな形「${t.textContent}」にしました`);
  };
  $('pairPick').onclick = (e) => {
    const o = e.target.closest('[data-pair]');
    if (!o) return;
    pl.kb.pair = o.dataset.pair;
    if (pl.kb.pair !== 'off') pl.kb.parts['1'].on = true;
    sendKb();
  };
  $('bands').addEventListener('pointerdown', bandDown);
  $('bands').addEventListener('pointermove', bandMove);
  $('bands').addEventListener('pointerup', bandUp);
  $('bands').addEventListener('pointercancel', bandUp);
  $('unused').onclick = (e) => {
    const c = e.target.closest('[data-ch]');
    if (!c) return;
    const p = pl.kb.parts[c.dataset.ch];
    p.on = true;
    if (c.dataset.ch === '2') pl.kb.pair = 'off';
    sendKb();
  };
}

async function sendKb() { take(await api.set_keyboard(pl.kb)); }

function bandChs() {
  const out = [];
  for (const ch of ['1', '2', '3', '4', '5']) {
    if (ch === '2' && pl.kb.pair !== 'off') continue;
    if (pl.kb.parts[ch].on) out.push(ch);
  }
  return out;
}

function drawBands() {
  const chs = bandChs();
  const label = { 1: '1 パルス', 2: '2 パルス', 3: '3 三角波', 4: '4 ノイズ', 5: '5 波形' };
  const pairName = { poly: '+2 ポリ', layer: '+2 ユニゾン' };
  $('bands').style.height = `${Math.max(1, chs.length) * 26}px`;
  $('bands').innerHTML = chs.map((ch, row) => {
    const p = pl.kb.parts[ch];
    const bg = ch === '1' && pl.kb.pair === 'poly' ? 'linear-gradient(var(--c1) 50%,var(--c2) 50%)'
      : ch === '1' && pl.kb.pair === 'layer' ? 'repeating-linear-gradient(90deg,var(--c1) 0 6px,var(--c2) 6px 12px)' : `var(--c${ch})`;
    const oct = p.shift / 12;
    const range = p.lo <= 0 && p.hi >= 127 ? '全部' : `${p.lo <= 0 ? '' : nn(p.lo)}〜${p.hi >= 127 ? '' : nn(p.hi)}`;
    return `<div class="band" data-ch="${ch}" style="top:${row * 26}px;left:${kpos(p.lo)}%;width:${kend(p.hi) - kpos(p.lo)}%;background:${bg}">`
      + `<span class="edge l" data-edge="l"></span>${label[ch]}${ch === '1' ? (pairName[pl.kb.pair] || '') : ''} <small>${range}</small>`
      + `<span class="oct"><i data-oct="-1" title="1オクターブ下げる">−</i><b>${oct === 0 ? '±0' : (oct > 0 ? `↑${oct}` : `↓${-oct}`)}</b><i data-oct="1" title="1オクターブ上げる">＋</i></span>`
      + `<span class="x" data-off title="この ch を使わない">✕</span><span class="edge r" data-edge="r"></span></div>`;
  }).join('') || '<div class="hint2">どの ch も使っていません。下の番号を押すと使います。</div>';
  const unused = ['1', '2', '3', '4', '5'].filter((ch) => !pl.kb.parts[ch].on && !(ch === '2' && pl.kb.pair !== 'off'));
  $('unused').innerHTML = unused.length
    ? '<span class="hint2">使わない:</span>' + unused.map((ch) => `<span class="chipbtn" style="--c:var(--c${ch})" data-ch="${ch}">＋ ${label[ch]}</span>`).join('')
    : '';
}

function bandDown(e) {
  const band = e.target.closest('.band');
  if (!band) return;
  const ch = band.dataset.ch, p = pl.kb.parts[ch];
  if (e.target.closest('[data-oct]')) {
    p.shift = Math.max(-24, Math.min(24, p.shift + 12 * +e.target.closest('[data-oct]').dataset.oct));
    sendKb();
    return;
  }
  if (e.target.closest('[data-off]')) {
    p.on = false;
    if (ch === '1' && pl.kb.pair !== 'off') pl.kb.pair = 'off';
    sendKb();
    return;
  }
  const edge = e.target.closest('[data-edge]');
  const r = $('bands').getBoundingClientRect();
  pl.drag = { ch, mode: edge ? edge.dataset.edge : 'move', lo: p.lo, hi: p.hi, x0: e.clientX, w: r.width, left: r.left, moved: false };
  try { $('bands').setPointerCapture(e.pointerId); } catch (_) { /* */ }
}

function bandMove(e) {
  const d = pl.drag;
  if (!d) return;
  const p = pl.kb.parts[d.ch];
  const pct = ((e.clientX - d.left) / d.w) * 100;
  const n = noteAtPct(pct);
  const ext = (v, lowSide) => (lowSide ? (v <= KB.LO ? 0 : v) : (v >= KB.HI ? 127 : v));   // 端まで持っていくと「端から全部」
  if (d.mode === 'l') p.lo = Math.min(ext(n, true), p.hi);
  else if (d.mode === 'r') p.hi = Math.max(ext(n, false), p.lo);
  else {
    const delta = noteAtPct(pct) - noteAtPct(((d.x0 - d.left) / d.w) * 100);
    if (delta === 0 && !d.moved) return;
    const span = Math.min(d.hi, KB.HI) - Math.max(d.lo, KB.LO);
    let lo = Math.max(d.lo, KB.LO) + delta;
    lo = Math.max(KB.LO, Math.min(KB.HI - span, lo));
    p.lo = d.lo <= 0 && delta <= 0 && lo === KB.LO ? 0 : lo;
    p.hi = d.hi >= 127 && delta >= 0 && lo + span === KB.HI ? 127 : lo + span;
  }
  d.moved = true;
  drawBands();
}

function bandUp() {
  const d = pl.drag;
  pl.drag = null;
  if (d && d.moved) sendKb();
}

// ---------------------------------------------------------------- ペダル・レバー
function drawControls(c) {
  const chips = (what, to, na = []) => '<span class="chips">' + [1, 2, 3, 4, 5].map((ch) =>
    `<span class="chip ${to.includes(ch) ? 'on' : ''} ${na.includes(ch) ? 'na' : ''}" style="--c:var(--c${ch})" data-what="${what}" data-ch="${ch}">${ch}</span>`).join('') + '</span>';
  const seg = (what, items, cur) => `<span class="seg">${items.map(([v, n]) =>
    `<button data-what="${what}" data-v="${v}" class="${String(v) === String(cur) ? 'on' : ''}">${n}</button>`).join('')}</span>`;
  $('ctlRows').innerHTML =
    `<div class="ctlrow"><span class="cname">サスティンペダル</span>${chips('pedal', c.pedal.to)}`
    + seg('pedal_use', [['hold', 'ホールド'], ['off', '使わない']], c.pedal.use)
    + '<span class="hint2">離したあとの伸びは各音色のホールド・タイム</span></div>'
    + `<div class="ctlrow"><span class="cname">ピッチベンド</span>${chips('bend', c.bend.to)}<span class="note">幅</span>`
    + seg('bend_range', [[2, '±2'], [7, '±7'], [12, '±12']], c.bend.range)
    + '<span class="hint2">半音。幅を変えられるのは ch1〜3(ch4 は決まった幅)</span></div>'
    + `<div class="ctlrow"><span class="cname">モジュレーション</span>${chips('mod', c.mod.to, c.mod.use === 'duty' ? [3, 4, 5] : [])}`
    + seg('mod_use', [['vibrato', 'ビブラート'], ['duty', 'デューティ比'], ['expression', 'エクスプレッション']], c.mod.use)
    + '<span class="hint2">ビブラートの深さ・速さは各音色で</span></div>';
  $('ctlRows').onclick = async (e) => {
    const el = e.target.closest('[data-what]');
    if (!el) return;
    const next = JSON.parse(JSON.stringify(c));
    const w = el.dataset.what;
    if (['pedal', 'bend', 'mod'].includes(w)) {
      const ch = +el.dataset.ch, to = next[w].to;
      next[w].to = to.includes(ch) ? to.filter((x) => x !== ch) : [...to, ch].sort();
    } else if (w === 'pedal_use') next.pedal.use = el.dataset.v;
    else if (w === 'bend_range') next.bend.range = +el.dataset.v;
    else if (w === 'mod_use') next.mod.use = el.dataset.v;
    take(await api.set_controls(next));
  };
}
