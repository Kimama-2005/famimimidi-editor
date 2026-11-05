// 音色をつくる場所(「1」〜「5」のタブ、SPEC_v2 7.3)。カードの中身・表示の判定・値の変換は Python(music/tonecards.py)。
'use strict';

const ed = { ch: null, view: null, widgets: {}, cards: {}, env: null, hasSus: true, wave: null, pending: {}, timer: null, folds: {} };
const help = (text) => `<span class="help" data-tip="${esc(text)}">?</span>`;

/** 送るのを間引く(つまみを動かしている間に Python を呼びすぎない)。最後の値は必ず送る */
function throttled(key, fn, ms = 40) {
  ed.pending[key] = fn;
  if (ed.timer) return;
  ed.timer = setTimeout(async () => {
    const jobs = ed.pending;
    ed.pending = {};
    ed.timer = null;
    for (const k in jobs) takeTone(await jobs[k]());
  }, ms);
}

function takeTone(r) {
  if (!r) return;
  if (r.error) { toast(r.error, 'danger'); return; }
  applyTone(r.tone);
  applyState(r.state, true);
}

async function loadTone(ch) {
  const v = await api.tone_view(ch);
  ed.ch = ch;
  ed.view = v;
  buildCards(v);
  applyTone(v.state);
}

/** app.js の applyState から呼ばれる。音色のタブを開いた・音色が入れ替わったときに作り直す */
window.toneSync = (st, fromTone) => {
  if (st.place === 'play') { ed.ch = null; return; }
  if (!fromTone) loadTone(st.place);
};

// ---------------------------------------------------------------- カード
function buildCards(v) {
  const root = $('cards');
  root.innerHTML = '';
  ed.widgets = {};
  ed.cards = {};
  for (const c of v.cards) {
    const card = document.createElement('div');
    card.className = 'win card' + (c.special === 'wave' ? ' wide' : '');
    card.dataset.card = c.key;
    const sw = c.switch || c.fold ? '<span class="sw"></span>' : '';
    card.innerHTML = `<h2>${esc(c.title)}${help(c.help)}${sw}</h2>`;
    ed.cards[c.key] = { el: card, def: c };
    if (c.switch) {
      const s = card.querySelector('.sw');
      s.onclick = () => throttled(c.switch, () => api.tone_set(ed.ch, c.switch, 'toggle', !s.classList.contains('on')), 0);
    } else if (c.fold) {
      const s = card.querySelector('.sw');
      const open = !!ed.folds[c.key];
      s.classList.toggle('on', open);
      card.classList.toggle('off', !open);
      s.onclick = () => { ed.folds[c.key] = !ed.folds[c.key]; s.classList.toggle('on'); card.classList.toggle('off'); };
    }
    if (c.special === 'duty') buildDuty(card, c.controls[0]);
    else if (c.special === 'env') { buildEnvelope(card); c.controls.forEach((x) => { if (!['atk', 'atklv', 'dec', 'sus', 'rel'].includes(x.key)) card.appendChild(buildRow(x)); }); }
    else if (c.special === 'wave') buildWave(card, c);
    else c.controls.forEach((x) => card.appendChild(buildRow(x)));
    root.appendChild(card);
  }
}

function buildRow(c) {
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = `<span class="name">${esc(c.label)}${help(c.help)}</span><span class="ctl"></span>`;
  const ctl = row.querySelector('.ctl');
  const w = { kind: c.kind, row, c };
  if (c.kind === 'toggle') {
    w.el = document.createElement('span');
    w.el.className = 'sw';
    w.el.onclick = () => throttled(c.key, () => api.tone_set(ed.ch, c.key, 'toggle', !w.el.classList.contains('on')), 0);
    ctl.appendChild(w.el);
  } else if (c.kind === 'choice' && c.choices.length <= 4) {
    w.kind = 'seg';
    w.el = document.createElement('span');
    w.el.className = 'seg';
    c.choices.forEach((label, i) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.onclick = () => throttled(c.key, () => api.tone_set(ed.ch, c.key, 'index', i), 0);
      w.el.appendChild(b);
    });
    ctl.appendChild(w.el);
  } else if (c.kind === 'choice') {
    w.el = document.createElement('select');
    c.choices.forEach((label, i) => w.el.add(new Option(label, i)));
    w.el.onchange = () => throttled(c.key, () => api.tone_set(ed.ch, c.key, 'index', +w.el.value), 0);
    ctl.appendChild(w.el);
  } else {
    const steps = c.kind === 'steps';
    const lo = steps ? 0 : c.lo, hi = steps ? c.steps.length - 1 : c.hi;
    ctl.innerHTML = `${c.left ? `<span class="end">${esc(c.left)}</span>` : ''}<input type="range" min="${lo}" max="${hi}">`
      + `${c.right ? `<span class="end">${esc(c.right)}</span>` : ''}<span class="num"></span>`;
    w.el = ctl.querySelector('input');
    w.num = ctl.querySelector('.num');
    w.label = (v) => (steps ? `${v}/${c.steps.length - 1}` : v);
    w.el.oninput = () => {
      const v = +w.el.value;
      w.num.textContent = w.label(v);
      throttled(c.key, () => api.tone_set(ed.ch, c.key, steps ? 'index' : 'value', v));
    };
  }
  ed.widgets[c.key] = w;
  return row;
}

// ---------------------------------------------------------------- デューティ比(波形の絵)
function buildDuty(card, c) {
  const box = document.createElement('div');
  box.className = 'duty';
  const sub = ['一番細く鋭い', 'ファミコンの定番', '丸い', '25% と同じ聞こえ方'];
  [12.5, 25, 50, 75].forEach((p, i) => {
    const hi = (p / 100) * 44;
    const d = document.createElement('div');
    d.className = 'pic';
    d.innerHTML = `<svg viewBox="0 0 100 40"><path d="M2 34 H6 V6 H${6 + hi} V34 H50 V6 H${50 + hi} V34 H98"/></svg>${p}%<small>${sub[i]}</small>`;
    d.onclick = () => throttled(c.key, () => api.tone_set(ed.ch, c.key, 'index', i), 0);
    box.appendChild(d);
  });
  card.appendChild(box);
  ed.widgets[c.key] = { kind: 'duty', el: box, c };
}

// ---------------------------------------------------------------- エンベロープ(グラフの点をつまむ)
const ENV = { W: 600, H: 200, TOP: 24, BOT: 176, X0: 20, K: 1.1, OFF: 440 };
function buildEnvelope(card) {
  card.insertAdjacentHTML('beforeend', `
    <svg class="env" id="envSvg" viewBox="0 0 ${ENV.W} ${ENV.H}">
      <line class="gl" x1="0" y1="${ENV.TOP}" x2="${ENV.W}" y2="${ENV.TOP}"/><line class="gl" x1="0" y1="${ENV.BOT}" x2="${ENV.W}" y2="${ENV.BOT}"/>
      <line class="gl" id="envOffLine" y1="${ENV.TOP - 10}" y2="${ENV.BOT}" stroke-dasharray="4 4"/>
      <path class="fill" id="envFill"/><path class="curve" id="envCurve"/>
      <text x="6" y="18">最大</text><text x="6" y="194">0</text><text id="envOffText" y="194">↑ 鍵盤を離す</text>
      <circle class="h" id="hL" r="8"><title>鳴り始めの音量</title></circle>
      <circle class="h" id="hA" r="8"><title>アタック(左右)</title></circle>
      <circle class="h" id="hD" r="8"><title>ディケイ(左右)/ サステイン(上下)</title></circle>
      <circle class="h" id="hR" r="8"><title>リリース(左右)</title></circle>
    </svg>
    <div class="envvals" id="envVals"></div>
    <div class="note">白い点をつまんで動かします。右へ行くほど長く、高さは音量です。</div>`);
  const svg = card.querySelector('svg');
  let drag = null;
  svg.querySelectorAll('.h').forEach((h) => h.addEventListener('pointerdown', (e) => {
    drag = h.id;
    h.classList.add('drag');
    try { svg.setPointerCapture(e.pointerId); } catch (_) { /* そのまま */ }
  }));
  svg.addEventListener('pointermove', (e) => {
    if (!drag || !ed.env) return;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const { x, y } = pt.matrixTransform(svg.getScreenCTM().inverse());
    const v = ed.env;
    const lvl = (yy) => Math.round(Math.max(0, Math.min(15, ((ENV.BOT - yy) / (ENV.BOT - ENV.TOP)) * 15)));
    const time = (px) => Math.round(Math.max(0, Math.min(127, px / ENV.K)));
    if (drag === 'hA') v[73] = time(x - ENV.X0);
    if (drag === 'hL') v[12] = lvl(y) * 8 + 4;
    if (drag === 'hD' && ed.hasSus) {
      v[79] = Math.min(127, lvl(y) * 8 + 4 + (lvl(y) === 15 ? 3 : 0));
      if (v[79] < 120) v[75] = time(x - ENV.X0 - v[73] * ENV.K);
    }
    if (drag === 'hR') v[72] = time(x - envOff());
    drawEnvelope();
    const upd = {};
    [73, 12, 75, 79, 72].forEach((k) => { if (v[k] !== undefined) upd[k] = v[k]; });
    throttled('env', () => api.tone_env(ed.ch, upd));
  });
  const end = () => { if (drag) $(drag).classList.remove('drag'); drag = null; };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
}
function envOff() {
  const v = ed.env;
  return Math.max(ENV.OFF, ENV.X0 + (v[73] + (v[79] < 120 ? v[75] : 0)) * ENV.K + 40);
}
function drawEnvelope() {
  const v = ed.env;
  if (!v || !$('envCurve')) return;
  const lv = (x) => ENV.BOT - (Math.min(15, Math.floor(x / 8)) / 15) * (ENV.BOT - ENV.TOP);
  const hasAtk = v[73] > 0, hasDec = v[79] < 120, hasLvl = v[12] !== undefined;
  const y0 = hasAtk && hasLvl ? lv(v[12]) : ENV.TOP;
  const xA = ENV.X0 + v[73] * ENV.K, ys = lv(v[79]);
  const xD = xA + (hasDec ? v[75] * ENV.K : 0), xOff = envOff(), xR = Math.min(xOff + v[72] * ENV.K, ENV.W - 6);
  const d = `M${ENV.X0} ${ENV.BOT} L${ENV.X0} ${y0} L${xA} ${ENV.TOP} L${xD} ${ys} L${xOff} ${ys} L${xR} ${ENV.BOT}`;
  $('envCurve').setAttribute('d', d);
  $('envFill').setAttribute('d', d + ' Z');
  const put = (id, x, y, show = true) => { const h = $(id); h.setAttribute('cx', x); h.setAttribute('cy', y); h.style.display = show ? '' : 'none'; };
  put('hL', ENV.X0, y0, hasAtk && hasLvl);
  put('hA', xA, ENV.TOP);
  put('hD', xD, ys, ed.hasSus);
  put('hR', xR, ENV.BOT);
  $('envOffLine').setAttribute('x1', xOff);
  $('envOffLine').setAttribute('x2', xOff);
  $('envOffText').setAttribute('x', xOff - 8);
  const word = (n, a, b, c) => (n === 0 ? a : n < 40 ? b : c);
  $('envVals').innerHTML = `<span>アタック <b>${word(v[73], 'すぐ', '短め', 'ゆっくり')}</b></span>`
    + (ed.hasSus ? `<span>ディケイ <b>${hasDec ? word(v[75], 'すぐ', '短め', 'ゆっくり') : '―'}</b></span>`
      + `<span>サステイン <b>${Math.round((Math.min(15, Math.floor(v[79] / 8)) / 15) * 100)}%</b></span>` : '')
    + `<span>リリース <b>${word(v[72], 'すぐ消える', '短め', '長い余韻')}</b></span>`
    + (ed.hasSus ? '' : ' <span class="note">(三角波は音量の段階が無いので、鳴る/鳴らないだけ)</span>');
}

// ---------------------------------------------------------------- 波形メモリの波形(ch5)
function buildWave(card, c) {
  const box = document.createElement('div');
  box.className = 'wavebox';
  let bars = '';
  for (let i = 0; i < 16; i++) bars += `<rect class="wbar" data-i="${i}" x="${i}" width=".9"/><rect class="wtop" data-t="${i}" x="${i}" width=".9" height=".5"/>`;
  box.innerHTML = `<svg viewBox="0 0 16 16" preserveAspectRatio="none" id="waveSvg">${bars}</svg>
    <div class="wavectl"><div id="waveRows"></div>
      <div class="note">おまかせの波形</div><div class="presets" id="wavePresets"></div>
      <button class="btn" id="waveReg" title="カートリッジの 61〜76 に登録(電源を切っても残る)">カートリッジに登録…</button>
      <div class="note" id="waveNone"></div></div>`;
  card.appendChild(box);
  c.controls.forEach((x) => box.querySelector('#waveRows').appendChild(buildRow(x)));
  box.querySelector('#wavePresets').innerHTML = ed.view.wave_presets.map(([n], i) => `<button class="btn" data-w="${i}">${esc(n)}</button>`).join('');
  box.querySelector('#wavePresets').onclick = (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    ed.wave = [...ed.view.wave_presets[+b.dataset.w][1]];
    drawWave();
    throttled('wave', () => api.set_wave(ed.wave), 0);
  };
  box.querySelector('#waveReg').onclick = () => { if (!ed.wave) { toast('先に波形を描いてください'); return; } openWaveRegister((ed.view.state && ed.view.state.name) || ''); };
  const svg = box.querySelector('svg');
  let down = false;
  const at = (e) => {
    const r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(15, Math.floor(((e.clientX - r.left) / r.width) * 16)));
    const v = Math.max(0, Math.min(15, Math.round(15 - ((e.clientY - r.top) / r.height) * 15)));
    if (!ed.wave) ed.wave = Array(16).fill(8);
    if (ed.wave[i] === v) return;
    ed.wave[i] = v;
    drawWave();
    throttled('wave', () => api.set_wave(ed.wave), 60);
  };
  svg.addEventListener('pointerdown', (e) => { down = true; try { svg.setPointerCapture(e.pointerId); } catch (_) { /* */ } at(e); });
  svg.addEventListener('pointermove', (e) => { if (down) at(e); });
  svg.addEventListener('pointerup', () => { down = false; });
  svg.addEventListener('pointercancel', () => { down = false; });
}
function drawWave() {
  const w = ed.wave || Array(16).fill(0);
  for (let i = 0; i < 16; i++) {
    const bar = document.querySelector(`#waveSvg [data-i="${i}"]`), top = document.querySelector(`#waveSvg [data-t="${i}"]`);
    if (!bar) return;
    const h = Math.max(0.3, w[i]);
    bar.setAttribute('y', 16 - h);
    bar.setAttribute('height', h);
    top.setAttribute('y', 16 - h);
  }
  const none = $('waveNone');
  if (none) none.textContent = ed.wave ? '' : 'この音色には波形が入っていません(描くと入ります)';
}

// ---------------------------------------------------------------- いまの値を画面に
function applyTone(st) {
  if (!st || !ed.view) return;
  for (const [key, card] of Object.entries(ed.cards)) {
    if (card.def.switch) {
      const on = st.cards[key] && st.cards[key].on;
      card.el.querySelector('.sw').classList.toggle('on', on);
      card.el.classList.toggle('off', !on);
    }
  }
  for (const [key, w] of Object.entries(ed.widgets)) {
    const s = st.controls[key];
    if (!s) continue;
    if (w.row) w.row.style.display = s.show ? '' : 'none';
    if (w.kind === 'toggle') w.el.classList.toggle('on', s.on);
    else if (w.kind === 'seg' || w.kind === 'duty') [...w.el.children].forEach((b, i) => b.classList.toggle('on', i === s.index));
    else if (w.kind === 'choice') w.el.value = s.index;
    else if (document.activeElement !== w.el) {
      const v = w.kind === 'steps' ? s.index : s.value;
      w.el.value = v;
      w.num.textContent = w.label(v);
    }
  }
  if (st.env && '73' in st.env) {
    ed.hasSus = st.has_sus;
    ed.env = { 73: st.env['73'], 12: st.env['12'], 75: st.env['75'] ?? 0, 79: st.env['79'] ?? 127, 72: st.env['72'] };
    drawEnvelope();
  }
  if ('wave' in st && $('waveSvg')) {
    ed.wave = st.wave ? [...st.wave] : null;
    drawWave();
  }
}
