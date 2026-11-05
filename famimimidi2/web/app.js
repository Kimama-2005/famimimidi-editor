// FAMIMIMIDI SOUND EDITOR(作り直し版)— 画面側。値の計算はしない。Python の Bridge を pywebview.api で呼ぶ。
'use strict';

const $ = (id) => document.getElementById(id);
const CHN = { 1: '1 パルス', 2: '2 パルス', 3: '3 三角波', 4: '4 ノイズ', 5: '5 DPCM/波形' };
const KB_RANGE = { play: [48, 84], 1: [48, 84], 2: [48, 84], 3: [36, 72], 4: [36, 72], 5: [48, 84] };
const S = { state: null, side: null, sel: null, vel: 100, init: null };
let api = null;

// ---------- お知らせ ----------
let toastTimer = null;
function toast(msg, kind = '') {
  const t = $('toast');
  t.textContent = msg;
  t.className = kind;
  t.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.style.display = 'none'), kind === 'danger' ? 6000 : 3000);
}
window.toast = toast;

// ---------- 「?」の説明(1枚の吹き出しを画面に収まる位置へ) ----------
function showTip(el) {
  const tip = $('tip');
  tip.textContent = el.dataset.tip || '';
  tip.style.display = 'block';
  tip.style.maxWidth = `${Math.min(300, window.innerWidth - 16)}px`;
  const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight, gap = 6, m = 8;
  let x = r.right + gap;
  if (x + w > window.innerWidth - m) x = r.left - gap - w;
  x = Math.max(m, Math.min(x, window.innerWidth - m - w));
  let y = r.top - 6;
  if (y + h > window.innerHeight - m) y = window.innerHeight - m - h;
  tip.style.left = `${x}px`;
  tip.style.top = `${Math.max(m, y)}px`;
}
function hideTip() { $('tip').style.display = 'none'; }
document.addEventListener('mouseover', (e) => { const h = e.target.closest && e.target.closest('.help'); if (h) showTip(h); });
document.addEventListener('mouseout', (e) => { if (e.target.closest && e.target.closest('.help')) hideTip(); });
document.addEventListener('scroll', hideTip, true);

// ---------- 重ねて出す画面 ----------
function openOv(id) { $(id).classList.add('open'); }
function closeOv(id) { $(id).classList.remove('open'); }
document.addEventListener('click', (e) => {
  if (e.target.matches('[data-close]')) e.target.closest('.overlay').classList.remove('open');
});

/** 名前を入れる / 確かめる。→ 入れた文字(確かめるだけなら true)、やめたら null */
function ask({ title, text = '', value = null, ok = 'OK' }) {
  return new Promise((resolve) => {
    $('askTitle').textContent = title;
    $('askText').textContent = text;
    const inp = $('askInput');
    inp.hidden = value === null;
    inp.value = value ?? '';
    $('askYes').textContent = ok;
    openOv('ovAsk');
    if (!inp.hidden) setTimeout(() => { inp.focus(); inp.select(); }, 0);
    const done = (v) => { closeOv('ovAsk'); $('askYes').onclick = $('askNo').onclick = inp.onkeydown = null; resolve(v); };
    $('askYes').onclick = () => done(inp.hidden ? true : inp.value);
    $('askNo').onclick = () => done(null);
    inp.onkeydown = (e) => { if (e.key === 'Enter') done(inp.value); if (e.key === 'Escape') done(null); };
  });
}

// ---------- Python の答えを画面に ----------
/** Bridge の答え({state, side} か state か {error})を画面に入れる */
function take(r) {
  if (!r) return r;
  if (r.error) { toast(r.error, 'danger'); return r; }
  if (r.side) applySide(r.side, r.selected);
  applyState(r.state || r);
  return r;
}

function applyState(st, fromTone = false) {
  if (!st || !st.session) return;
  S.state = st;
  document.documentElement.dataset.theme = st.prefs.theme;
  renderStatus(st.connection);
  renderSet(st.session);
  renderTabs(st);
  renderPages(st);
  renderKb(st);
  renderSettings(st.prefs);
  if (window.toneSync) toneSync(st, fromTone);
  if (window.renderPlay) renderPlay(st);
}

function renderStatus(c) {
  const el = $('status');
  if (window.vfcSync) vfcSync(c);
  if (c.out) {
    el.textContent = (c.virtual ? '🎮 仮想ファミコン' : `${c.out}`) + (c.in ? ` ← ${c.in}` : '(入力なし)');
    el.className = 'status ok clickable';
  } else {
    el.textContent = '未接続(押して接続)';
    el.className = 'status ng clickable';
  }
}

function renderSet(s) {
  $('setName').textContent = s.name || '(名前なし)';
  $('setDirty').hidden = !s.dirty;
  $('link12').classList.toggle('on', s.link12);
  $('link12').title = s.link12
    ? '紐付け中: ch2 も ch1 の音色で鳴ります。押すと外して、保管していた ch2 の音色に戻します'
    : '紐付け: ch2 も ch1 の音色で鳴らす(ch2 の音色は保管され、外すと戻ります)';
}

function renderTabs(st) {
  const p = String(st.place);
  document.querySelectorAll('#tabs .tab').forEach((t) => t.classList.toggle('on', t.dataset.p === p));
}

function renderPages(st) {
  const s = st.session, place = st.place;
  $('p-play').classList.toggle('on', place === 'play');
  $('p-tone').classList.toggle('on', place !== 'play');
  // ♪ 演奏セット
  document.querySelectorAll('#howSeg button').forEach((b) => b.classList.toggle('on', (b.dataset.h === 'chord') === s.chord_active));
  $('howMap').hidden = s.chord_active;
  $('howChord').hidden = !s.chord_active;
  $('chList').innerHTML = s.slots.map((sl) => {
    const name = sl.linked ? `${s.slots[0].name || '(既定値)'}(ch1 と同じ)` : (sl.name || '(既定値)');
    return `<div style="border-color:var(--c${sl.ch})" data-go="${sl.ch}" title="押すと ${CHN[sl.ch]} のタブへ">`
      + `<b style="color:var(--c${sl.ch})">${CHN[sl.ch]}${sl.linked ? ' 🔗' : ''}</b>${esc(name)}`
      + (sl.silent ? '<span class="sil"> 音量0</span>' : '') + '</div>';
  }).join('');
  // 1〜5
  if (place !== 'play') {
    const sl = s.slots[place - 1];
    $('toneCh').textContent = CHN[place];
    $('toneName').textContent = sl.linked ? (s.slots[0].name || '(既定値)') : (sl.name || '(既定値)');
    let ln = '';
    if (s.link12 && place === 1) ln = '🔗 ch2 にも同じ変更が入ります';
    if (s.link12 && place === 2) ln = `🔗 ch1 の音色を使用中。ch2 の音色「${sl.kept || '(既定値)'}」は保管中(🔗 を外すと戻ります)`;
    $('linkNote').textContent = ln;
  }
}

function renderSettings(prefs) {
  if (!S.init) return;
  $('themeSeg').innerHTML = S.init.themes.map(([k, n]) => `<button data-v="${k}" class="${k === prefs.theme ? 'on' : ''}">${n}</button>`).join('');
  $('offsetSeg').innerHTML = S.init.offsets.map(([k, n]) => `<button data-v="${k}" class="${k === prefs.ch_offset ? 'on' : ''}">${n}</button>`).join('');
}

function esc(s) { return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

// ---------- 左の一覧 ----------
function applySide(side, selected) {
  S.side = side;
  const ids = side.items.filter((i) => !i.header).map((i) => i.id);
  if (selected && ids.includes(selected)) S.sel = selected;
  else if (!ids.includes(S.sel)) S.sel = (side.items.find((i) => i.current) || {}).id || null;
  renderSide();
}

function renderSide() {
  const side = S.side;
  if (!side) return;
  const isPlay = side.place === 'play';
  $('sideTitle').innerHTML = isPlay ? '演奏セット'
    : `<i class="dot" style="display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;background:var(--c${side.place})"></i>${esc(side.title)}`;
  const q = $('sideSearch').value.trim().toLowerCase();
  const items = side.items.filter((i) => i.header || !q || i.name.toLowerCase().includes(q));
  $('sideList').innerHTML = items.length
    ? items.map((i) => i.header ? `<li class="note head">${esc(i.name)}</li>` : `<li data-id="${esc(i.id)}" class="${i.id === S.sel ? 'sel' : ''} ${i.current ? 'cur' : ''}">${esc(i.name || '(名前なし)')}`
      + (i.sub ? ` <small>${esc(i.sub)}</small>` : '') + '</li>').join('')
    : '<li class="note" style="cursor:default">(まだありません)</li>';
  const btns = isPlay
    ? [['load', '読み込む'], ['over', '上書き保存'], ['new', '新しく保存'], ['rename', '名前を変える'], ['del', '削除']]
    : [['put', 'この ch に入れる'], ['over', '上書き保存'], ['new', '新しく保存'], ['rename', '名前を変える'], ['del', '削除']];
  $('sideBtns').innerHTML = btns.map(([k, n], i) => `<button class="btn${i === 0 ? ' main' : ''}" data-act="${k}">${n}</button>`).join('');
  const it = side.items.find((i) => i.id === S.sel);
  let info = side.info;
  if (it) {
    info = it.name + (it.notes ? `\n${it.notes}` : '');
    if (isPlay && it.tones) info += '\n' + it.tones.map((n, k) => `${k + 1}: ${n || '(既定値)'}`).join('\n');
  }
  $('sideInfo').textContent = info;
}

async function sideAction(act) {
  const side = S.side, isPlay = side.place === 'play', id = S.sel;
  const it = side.items.find((i) => i.id === id);
  const need = () => { if (!it) toast('左の一覧で選んでください'); return !!it; };
  if (act === 'load' && need()) {
    if (S.state.session.dirty && !(await ask({ title: '読み込みますか?', text: 'いまの演奏セットの変更は保存していません。読み込むと消えます。', ok: '読み込む' }))) return;
    take(await api.load_performance(id));
    toast(`「${it.name}」を読み込んで送りました`);
  } else if (act === 'put' && need()) {
    take(await api.put_tone(side.place, id));
  } else if (act === 'new') {
    const cur = isPlay ? S.state.session.name : (S.state.session.slots[side.place - 1].name);
    const name = await ask({ title: isPlay ? '演奏セットとして新しく保存' : `${CHN[side.place]} の音色を新しく保存`, value: cur || '', ok: '保存' });
    if (name === null) return;
    take(await (isPlay ? api.save_performance_new(name) : api.save_tone_new(side.place, name)));
    toast('保存しました');
  } else if (act === 'over' && need()) {
    const what = isPlay ? 'いまの演奏セット' : `いまの ${CHN[side.place]} の音色`;
    if (!(await ask({ title: '上書き保存', text: `「${it.name}」を${what}で上書きします。`, ok: '上書き' }))) return;
    take(await (isPlay ? api.overwrite_performance(id) : api.overwrite_tone(side.place, id)));
    toast('上書き保存しました');
  } else if (act === 'rename' && need()) {
    const name = await ask({ title: '名前を変える', value: it.name, ok: '変える' });
    if (name === null) return;
    take(await (isPlay ? api.rename_performance(id, name) : api.rename_tone(id, name)));
  } else if (act === 'del' && need()) {
    if (!(await ask({ title: '削除', text: `「${it.name}」をライブラリから削除します。元に戻せません。`, ok: '削除' }))) return;
    take(await (isPlay ? api.delete_performance(id) : api.delete_tone(id)));
  }
}

// ---------- 下の鍵盤 ----------
const isBlack = (n) => [1, 3, 6, 8, 10].includes(n % 12);
const down = new Map();       // pointerId -> note

function renderKb(st) {
  const kb = $('kb'), view = st.keyboard;
  $('kbState').textContent = view.text;
  $('kbFollow').hidden = st.place === 'play';
  $('kbFollowSeg').querySelectorAll('button').forEach((b) => b.classList.toggle('on', (b.dataset.v === '1') === !!st.prefs.kb_follow));
  const [lo, hi] = KB_RANGE[st.place];
  const whites = [];
  for (let n = lo; n <= hi; n++) if (!isBlack(n)) whites.push(n);
  const W = 100 / whites.length;
  const zone = (n) => {
    const chs = view.zones[String(n)];
    if (!chs || view.mode === 'chord') return { cls: '', style: '' };
    if (chs.length >= 2) return { cls: ' zz', style: `--zc:color-mix(in srgb, var(--c${chs[0]}) 45%, #fff);--zc2:color-mix(in srgb, var(--c${chs[1]}) 45%, #fff)` };
    return { cls: ' z', style: `--zc:color-mix(in srgb, var(--c${chs[0]}) 45%, #fff)` };
  };
  const label = (n) => (view.labels && view.labels[String(n)] ? `<em>${esc(view.labels[String(n)])}</em>` : '');
  let html = '';
  whites.forEach((n) => {
    const z = zone(n);
    const quiet = view.mode !== 'chord' && !view.zones[String(n)] ? ' silent' : '';
    html += `<div class="w${z.cls}${quiet}" data-n="${n}" style="${z.style}">${label(n)}${n % 12 === 0 ? `<span>C${Math.floor(n / 12) - 1}</span>` : ''}</div>`;
  });
  for (let n = lo; n <= hi; n++) {
    if (!isBlack(n)) continue;
    const i = whites.indexOf(n - 1), z = zone(n);
    const quiet = view.mode !== 'chord' && !view.zones[String(n)] ? ' silent' : '';
    html += `<div class="b${z.cls}${quiet}" data-n="${n}" style="left:${(i + 1) * W - W * 0.32}%;width:${W * 0.64}%;${z.style}">${label(n)}</div>`;
  }
  kb.innerHTML = html;
  if (view.mode === 'chord' && typeof cm !== 'undefined' && cm.view) onChordState(cm.view.state);   // いま・次の鍵を光らせ直す
}

function keyAt(e) {
  // 押したまま横へすべらせたときは、指の下の鍵(つかんだ鍵ではない)
  // 鍵の中の文字(「C4」)の上を押しても、その鍵にする
  let el = document.elementFromPoint(e.clientX, e.clientY);
  if (!(el && el.closest && el.closest('#kb'))) el = e.type === 'pointerdown' ? e.target : null;
  const key = el && el.closest ? el.closest('#kb [data-n]') : null;
  return key ? +key.dataset.n : null;
}
function press(id, n) {
  const old = down.get(id);
  if (old === n) return;
  if (old !== undefined) release(id);
  if (n === null) return;
  down.set(id, n);
  const el = $('kb').querySelector(`[data-n="${n}"]`);
  if (el) el.classList.add('down');
  api.note(n, S.vel, true);
}
function release(id) {
  const n = down.get(id);
  if (n === undefined) return;
  down.delete(id);
  const el = $('kb').querySelector(`[data-n="${n}"]`);
  if (el) el.classList.remove('down');
  api.note(n, 0, false);
}

// ---------- 送信ログ ----------
window.onLog = (lines) => {
  const log = $('log');
  const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
  const frag = document.createDocumentFragment();
  lines.forEach((ln) => {
    const d = document.createElement('div');
    d.textContent = ln;
    if (/\s(遮断|失敗|未送信)\s/.test(ln)) d.className = 'blocked';
    else if (/\s(----|省略|IN)\s/.test(ln)) d.className = 'note';
    frag.appendChild(d);
  });
  log.appendChild(frag);
  while (log.childNodes.length > 2000) log.removeChild(log.firstChild);
  if (atEnd) log.scrollTop = log.scrollHeight;
};

// ---------- 接続 ----------
function fillPorts(p) {
  const opt = (names, want) => names.map((n) => `<option ${n === want ? 'selected' : ''}>${esc(n)}</option>`).join('');
  $('outSel').innerHTML = opt(p.out, p.want_out);
  $('inSel').innerHTML = '<option value="">(使わない)</option>' + opt(p.in, p.want_in);
}

async function go(place) {
  for (const id of [...down.keys()]) release(id);
  take(await api.set_place(place));
}

window.refresh = async () => { take({ state: await api.state(), side: await api.side() }); };

// ---------- はじめ ----------
window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  const init = await api.init();
  S.init = init;
  fillPorts(init.ports);
  take({ state: init.state, side: init.side });
  init.notes.forEach((n, i) => setTimeout(() => toast(n), i * 3200));
  if (init.other_apps.length) {
    toast(`${init.other_apps.join('・')} が起動しています。鍵盤の演奏を ふぁみみみっでぃ へ直接流していると、このアプリと二重に鳴ります。使わないときは閉じてください。`, 'danger');
  }

  $('tabs').onclick = (e) => { const t = e.target.closest('.tab'); if (t) go(t.dataset.p === 'play' ? 'play' : +t.dataset.p); };
  $('link12').onclick = async () => take(await api.toggle_link12());
  $('chList').onclick = (e) => { const d = e.target.closest('[data-go]'); if (d) go(+d.dataset.go); };
  $('howSeg').onclick = async (e) => { const b = e.target.closest('button'); if (b) take(await api.set_chord_active(b.dataset.h === 'chord')); };
  $('btnResend').onclick = async () => { take(await api.resend()); toast('5ch 分の音色を送り直しました'); };
  $('btnReset').onclick = async () => {
    if (await ask({ title: '初期化', text: `${CHN[S.state.place]} の音色を、全部の項目が電源 ON のときの値の音にして送ります。`, ok: '初期化' })) {
      take(await api.reset_tone(S.state.place));
    }
  };
  $('btnPanic').onclick = async () => { if (!(await api.panic())) toast('書き込み中なので送りませんでした'); };
  $('btnSettings').onclick = () => openOv('ovSettings');
  $('status').onclick = async () => { fillPorts(await api.ports()); openOv('ovConnect'); };
  $('btnRefresh').onclick = async () => fillPorts(await api.ports());
  $('btnConnect').onclick = async () => {
    const r = await api.connect($('outSel').value, $('inSel').value);
    take(r.state);
    if (!r.ok) toast(r.message, 'danger');
    else { toast(r.message || 'つなぎました。作業中の演奏を送りました'); closeOv('ovConnect'); }
  };
  $('btnDisconnect').onclick = async () => { take(await api.disconnect()); closeOv('ovConnect'); };
  $('themeSeg').onclick = async (e) => { const b = e.target.closest('button'); if (b) take(await api.set_theme(b.dataset.v)); };
  $('kbFollowSeg').onclick = async (e) => { const b = e.target.closest('button'); if (b) take(await api.set_kb_follow(b.dataset.v === '1')); };
  $('offsetSeg').onclick = async (e) => { const b = e.target.closest('button'); if (b) take(await api.set_offset(+b.dataset.v)); };
  $('sideList').onclick = (e) => { const li = e.target.closest('li[data-id]'); if (li) { S.sel = li.dataset.id; renderSide(); } };
  $('sideList').ondblclick = (e) => { const li = e.target.closest('li[data-id]'); if (li) { S.sel = li.dataset.id; sideAction(S.side.place === 'play' ? 'load' : 'put'); } };
  $('sideBtns').onclick = (e) => { const b = e.target.closest('button'); if (b) sideAction(b.dataset.act); };
  $('sideSearch').oninput = renderSide;
  $('logHead').onclick = () => $('logWin').classList.toggle('collapsed');
  $('vel').oninput = (e) => { S.vel = +e.target.value; $('velNum').textContent = S.vel; };
  const kb = $('kb');
  kb.addEventListener('pointerdown', (e) => {
    try { kb.setPointerCapture(e.pointerId); } catch (_) { /* つかめなくても鳴らす */ }
    press(e.pointerId, keyAt(e));
  });
  kb.addEventListener('pointermove', (e) => { if (down.has(e.pointerId)) press(e.pointerId, keyAt(e)); });
  kb.addEventListener('pointerup', (e) => release(e.pointerId));
  kb.addEventListener('pointercancel', (e) => release(e.pointerId));
  document.addEventListener('keydown', async (e) => {
    if (e.target.matches('input[type=text], textarea, select') || document.querySelector('.overlay.open')) return;
    if (e.code === 'Space' && S.state.place === 'play') {
      e.preventDefault();
      take(await api.set_chord_active(!S.state.session.chord_active));
    }
  });
});
