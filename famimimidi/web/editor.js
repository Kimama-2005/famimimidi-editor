// 音色エディタ(C2)。表示・非表示の判定と値の変換は Python(editor.py)が行い、ここは見せ方だけ。
'use strict';

const ed = { ch: 1, spec: null, state: null, view: 'easy', presets: [], widgets: {}, sending: null };

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const help = (text) => `<span class="help" data-tip="${esc(text)}">?</span>`;

// 送信を間引く(ドラッグ中などに Python を呼びすぎない)。最後の値は必ず送る
function throttled(key, fn, ms = 40) {
  ed.pending = ed.pending || {};
  ed.pending[key] = fn;
  if (ed.timer) return;
  ed.timer = setTimeout(async () => {
    const jobs = ed.pending;
    ed.pending = {};
    ed.timer = null;
    for (const k in jobs) applyState(await jobs[k]());
  }, ms);
}

async function loadEditor(ch) {
  ed.ch = ch;
  const r = await api.editor(ch);
  ed.spec = r.spec;
  ed.presets = r.presets;
  ed.view = r.view;
  renderPresets();
  renderEasy();
  renderDetail();
  showView(ed.view, false);
  applyState(r.state);
}

// ---------- おまかせ ----------
function renderPresets() {
  const sel = $('presetSel');
  sel.innerHTML = '';
  if (!ed.presets.length) sel.add(new Option('(このチャンネル用はまだありません)', ''));
  ed.presets.forEach((p) => sel.add(new Option(`[${p.group}] ${p.name}`, p.id)));
  sel.onchange = () => { const p = ed.presets.find((x) => x.id === sel.value); $('presetDesc').textContent = p ? p.desc : ''; };
  sel.onchange();
}

// ---------- かんたん表示 ----------
function renderEasy() {
  const root = $('easyView');
  root.innerHTML = '';
  ed.widgets = {};
  // エンベロープを一番上(横幅いっぱい)に、あとは定義の順
  const groups = [...ed.spec.groups].sort((a, b) => (b.key === 'env') - (a.key === 'env'));
  for (const g of groups) {
    const card = document.createElement('div');
    card.className = 'win card' + (g.key === 'env' ? ' wide' : '');
    card.dataset.group = g.key;
    const toggle = g.controls[0].kind === 'toggle' ? g.controls[0] : null;
    card.innerHTML = `<h2>${esc(g.title)}${help(g.help)}${toggle ? `<span class="sw" data-key="${toggle.key}"></span>` : ''}</h2>`;
    if (toggle) {
      const sw = card.querySelector('.sw');
      sw.onclick = async () => applyState(await api.ctl(ed.ch, toggle.key, 'toggle', !sw.classList.contains('on')));
      ed.widgets[toggle.key] = { kind: 'cardtoggle', el: sw, card };
    }
    if (g.key === 'env') buildEnvelope(card, g);
    else if (g.key === 'duty') buildDuty(card, g.controls[0]);
    else g.controls.forEach((c) => { if (c !== toggle) card.appendChild(buildRow(c)); });
    root.appendChild(card);
  }
}

function buildRow(c) {
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = `<span class="name" title="${esc(c.label)}">${esc(c.label)}${help(c.help)}</span><span class="ctl"></span>`;
  const ctl = row.querySelector('.ctl');
  const w = { kind: c.kind, row, c };
  if (c.kind === 'toggle') {
    w.el = document.createElement('span');
    w.el.className = 'sw';
    w.el.onclick = async () => applyState(await api.ctl(ed.ch, c.key, 'toggle', !w.el.classList.contains('on')));
    ctl.appendChild(w.el);
  } else if (c.kind === 'choice' && c.choices.length <= 4) {
    w.kind = 'seg';
    w.el = document.createElement('div');
    w.el.className = 'seg';
    c.choices.forEach((label, i) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.onclick = async () => applyState(await api.ctl(ed.ch, c.key, 'index', i));
      w.el.appendChild(b);
    });
    ctl.appendChild(w.el);
  } else if (c.kind === 'choice') {
    w.el = document.createElement('select');
    c.choices.forEach((label, i) => w.el.add(new Option(label, i)));
    w.el.onchange = async () => applyState(await api.ctl(ed.ch, c.key, 'index', +w.el.value));
    ctl.appendChild(w.el);
  } else {
    const steps = c.kind === 'steps';
    const numeric = steps && c.steps.every((s) => /^\d+$/.test(s));
    const lo = steps ? 0 : c.lo, hi = steps ? c.steps.length - 1 : c.hi;
    ctl.innerHTML = `${c.left ? `<span class="end">${esc(c.left)}</span>` : ''}<input type="range" min="${lo}" max="${hi}">` +
      `${c.right ? `<span class="end">${esc(c.right)}</span>` : ''}<span class="num"></span>`;
    w.el = ctl.querySelector('input');
    w.num = ctl.querySelector('.num');
    w.label = (v) => (steps ? (numeric ? `${c.steps[v]}/${c.steps.length - 1}` : c.steps[v]) : v);
    w.el.oninput = () => {
      const v = +w.el.value;
      w.num.textContent = w.label(v);
      throttled(c.key, () => api.ctl(ed.ch, c.key, steps ? 'index' : 'value', v));
    };
  }
  ed.widgets[c.key] = w;
  return row;
}

// ---------- デューティ(波形の絵) ----------
function buildDuty(card, c) {
  const box = document.createElement('div');
  box.className = 'duty';
  const sub = ['一番細く鋭い', 'ファミコンの定番', '丸い', '25%と同じ聞こえ方'];
  [12.5, 25, 50, 75].forEach((p, i) => {
    const hi = (p / 100) * 44;
    const d = document.createElement('div');
    d.className = 'pic';
    d.innerHTML = `<svg viewBox="0 0 100 40"><path d="M2 34 H6 V6 H${6 + hi} V34 H50 V6 H${50 + hi} V34 H98"/></svg>${p}%<small>${sub[i]}</small>`;
    d.onclick = async () => applyState(await api.ctl(ed.ch, c.key, 'index', i));
    box.appendChild(d);
  });
  card.appendChild(box);
  ed.widgets[c.key] = { kind: 'duty', el: box, c };
}

// ---------- エンベロープ(グラフの点をつまんで動かす) ----------
const ENV = { W: 600, H: 200, TOP: 24, BOT: 176, X0: 20, K: 1.1, OFF: 440 };
function buildEnvelope(card, g) {
  card.insertAdjacentHTML('beforeend', `
    <svg class="env" viewBox="0 0 ${ENV.W} ${ENV.H}">
      <line class="gl" x1="0" y1="${ENV.TOP}" x2="${ENV.W}" y2="${ENV.TOP}"/><line class="gl" x1="0" y1="${ENV.BOT}" x2="${ENV.W}" y2="${ENV.BOT}"/>
      <line class="gl" id="envOffLine" y1="${ENV.TOP - 10}" y2="${ENV.BOT}" stroke-dasharray="4 4"/>
      <path class="fill" id="envFill"/><path class="curve" id="envCurve"/>
      <text x="6" y="18">最大</text><text x="6" y="194">0</text><text id="envOffText" y="194">↑ 鍵盤を離す</text>
      <circle class="h" id="hL" r="8"><title>アタック・レベル(鳴り始めの音量)</title></circle>
      <circle class="h" id="hA" r="8"><title>アタック・タイム(左右)</title></circle>
      <circle class="h" id="hD" r="8"><title>ディケイ・タイム(左右)/ サスティン・レベル(上下)</title></circle>
      <circle class="h" id="hR" r="8"><title>リリース・タイム(左右)</title></circle>
    </svg>
    <div class="envvals" id="envVals"></div>
    <div class="note">白い点をつまんで動かします。時間は右へ行くほど長く(指数的に伸びる)、高さは音量です。数値は「詳細」でも変えられます。</div>`);
  const svg = card.querySelector('svg');
  let drag = null;
  svg.querySelectorAll('.h').forEach((h) => h.addEventListener('pointerdown', (e) => {
    drag = h.id;
    h.classList.add('drag');
    svg.setPointerCapture(e.pointerId);
  }));
  svg.addEventListener('pointermove', (e) => {
    if (!drag) return;
    // 画面の座標 → グラフの座標(横に伸びたときの中央寄せも含めて、SVG 自身の変換で正確に直す)
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const { x, y } = pt.matrixTransform(svg.getScreenCTM().inverse());
    const v = ed.env;
    const lvl = (yy) => Math.round(Math.max(0, Math.min(15, ((ENV.BOT - yy) / (ENV.BOT - ENV.TOP)) * 15)));
    const time = (px) => Math.round(Math.max(0, Math.min(127, px / ENV.K)));
    if (drag === 'hA') v[73] = time(x - ENV.X0);
    if (drag === 'hL') v[12] = lvl(y) * 8 + 4;
    if (drag === 'hD' && ed.envHasSus) {
      v[79] = lvl(y) * 8 + 4;
      if (v[79] < 120) v[75] = time(x - ENV.X0 - v[73] * ENV.K);
    }
    if (drag === 'hR') v[72] = time(x - envOff());
    drawEnvelope();
    const upd = { 73: v[73], 12: v[12], 75: v[75], 79: v[79], 72: v[72] };
    throttled('env', () => api.env(ed.ch, upd));
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
  const lv = (x) => ENV.BOT - (Math.floor(x / 8) / 15) * (ENV.BOT - ENV.TOP);
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
  put('hD', xD, ys, ed.envHasSus);          // 三角波(ch3)にはサスティン・レベルが無い(常に最大)
  put('hR', xR, ENV.BOT);
  $('envOffLine').setAttribute('x1', xOff); $('envOffLine').setAttribute('x2', xOff);
  $('envOffText').setAttribute('x', xOff - 8);
  $('envVals').innerHTML = `A(アタック) <b>${v[73]}</b>` + (hasAtk && hasLvl ? ` 鳴り始め <b>${Math.floor(v[12] / 8)}/15</b>` : '') +
    ` D(ディケイ) <b>${hasDec ? v[75] : '―'}</b>` + (ed.envHasSus ? ` S(サスティン) <b>${Math.floor(v[79] / 8)}/15</b>` : '') +
    ` R(リリース) <b>${v[72]}</b>` +
    (hasDec ? '' : ` <span class="note">(${ed.envHasSus ? 'サスティンが最大なので' : 'このチャンネルは減衰しないので'}ディケイは効きません)</span>`);
}

// ---------- 詳細表示 ----------
function renderDetail() {
  const box = $('detailView');
  const rows = ed.spec.detail.map((p) => {
    const ctl = p.labels
      ? `<select data-cc="${p.cc}">${p.labels.map((l, i) => `<option value="${i}">${esc(l)}</option>`).join('')}</select>`
      : `<input type="range" min="0" max="127" data-cc="${p.cc}"> <span class="num" data-num="${p.cc}"></span>`;
    return `<tr><td class="cc">CC#${p.cc}</td><td>${esc(p.name)}</td><td>${ctl}</td><td class="hint">${esc(p.hint || '')}</td></tr>`;
  }).join('');
  box.innerHTML = `<h2>詳細(全項目)</h2><table>${rows}</table>`;
  box.querySelectorAll('select[data-cc]').forEach((s) => (s.onchange = async () =>
    applyState(await api.detail_set(ed.ch, +s.dataset.cc, 'index', +s.value))));
  box.querySelectorAll('input[data-cc]').forEach((s) => (s.oninput = () => {
    box.querySelector(`[data-num="${s.dataset.cc}"]`).textContent = s.value;
    throttled('d' + s.dataset.cc, () => api.detail_set(ed.ch, +s.dataset.cc, 'value', +s.value));
  }));
}

function showView(v, save = true) {
  ed.view = v;
  $('easyView').style.display = v === 'easy' ? '' : 'none';
  $('detailView').style.display = v === 'detail' ? '' : 'none';
  $('viewSeg').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
  if (save) api.set_view(v);
}

// ---------- 状態を画面に反映 ----------
function applyState(s) {
  if (!s) return;
  ed.state = s;
  $('loaded').textContent = `音色: ${s.loaded || '(なし)'}`;
  for (const [key, w] of Object.entries(ed.widgets)) {
    const st = s.controls[key];
    if (!st) continue;
    if (w.row) w.row.style.display = st.show ? '' : 'none';
    if (w.kind === 'cardtoggle') {
      w.el.classList.toggle('on', st.on);
      w.card.classList.toggle('off', !st.on);
    } else if (w.kind === 'toggle') w.el.classList.toggle('on', st.on);
    else if (w.kind === 'seg') [...w.el.children].forEach((b, i) => b.classList.toggle('on', i === st.index));
    else if (w.kind === 'duty') [...w.el.children].forEach((b, i) => b.classList.toggle('on', i === st.index));
    else if (w.kind === 'choice') w.el.value = st.index;
    else if (document.activeElement !== w.el) {        // 動かしている最中のつまみは上書きしない
      const v = w.kind === 'steps' ? st.index : st.value;
      w.el.value = v;
      w.num.textContent = w.label(v);
    }
  }
  const vals = s.values;
  if ('73' in vals) {
    ed.envHasSus = '79' in vals;
    ed.env = { 73: vals['73'], 12: vals['12'], 75: vals['75'], 79: vals['79'] ?? 127, 72: vals['72'] };
    drawEnvelope();
  }
  $('detailView').querySelectorAll('[data-cc]').forEach((el) => {
    const d = s.detail[el.dataset.cc];
    if (!d || document.activeElement === el) return;
    if (el.tagName === 'SELECT') el.value = d.index;
    else { el.value = d.value; $('detailView').querySelector(`[data-num="${el.dataset.cc}"]`).textContent = d.value; }
  });
}
