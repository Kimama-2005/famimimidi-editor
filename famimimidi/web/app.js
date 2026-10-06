// FAMIMIMIDI SOUND EDITOR — 画面側。Python の Bridge を pywebview.api 経由で呼ぶ。
'use strict';

const $ = (id) => document.getElementById(id);
const state = { ch: 1, channels: [], base: { 1: 60, 2: 60, 3: 48, 4: 0, 5: 36 }, status: null, vel: 100 };
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

// ---------- 状態表示 ----------
function showStatus(s) {
  state.status = s;
  const el = $('status');
  if (s.out) {
    el.textContent = `${s.out} に接続中` + (s.in ? ` / 入力: ${s.in}` : ' / 入力なし');
    el.className = 'status ok';
  } else {
    el.textContent = '未接続(⚙ 接続と設定 から接続してください)';
    el.className = 'status ng';
  }
  $('thru').checked = s.thru;
  showPlay(s);
  document.querySelectorAll('#offsets input').forEach((r) => (r.checked = +r.value === s.offset));
  document.querySelectorAll('#themes input').forEach((r) => (r.checked = r.value === s.theme));
  document.documentElement.dataset.theme = s.theme;
}

function fillPorts(p) {
  const fill = (sel, names, want, none) => {
    sel.innerHTML = '';
    if (none) sel.add(new Option('(使わない)', ''));
    names.forEach((n) => sel.add(new Option(n, n)));
    if (want && names.includes(want)) sel.value = want;
  };
  fill($('outSel'), p.out, p.want_out, false);
  fill($('inSel'), p.in, p.want_in, true);
}

// ---------- 鍵盤の弾き方(割り当て表) ----------
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const noteName = (n) => `${NOTE_NAMES[n % 12]}${Math.floor(n / 12) - 1}`;
function showPlay(s) {
  const p = s.play;
  document.querySelectorAll('#playMode input').forEach((r) => (r.checked = r.value === p.mode));
  $('playPair').value = p.pair;
  for (let ch = 1; ch <= 5; ch++) {
    const q = p.parts[ch], row = $('mapTable').querySelector(`tr[data-ch="${ch}"]`);
    const follow = ch === 2 && p.pair !== 'off';
    row.querySelector('.on').checked = q.on;
    row.querySelector('.lo').value = q.lo;
    row.querySelector('.hi').value = q.hi;
    row.querySelector('.shift').value = q.shift;
    row.querySelector('.ctl').checked = q.ctl;
    row.querySelectorAll('input, select').forEach((e) => (e.disabled = follow));
    row.querySelector('.follow').style.display = follow ? '' : 'none';
    row.querySelector('.own').style.display = follow ? 'none' : '';
    row.classList.toggle('off', !follow && !q.on);
  }
  $('layerRow').style.display = p.mode === 'map' && p.pair === 'layer' ? '' : 'none';
  $('playChip').textContent = `外部鍵盤: ${s.play_text}`;
  $('playChip').title = `外部の鍵盤(microKEY2 など)の演奏: ${s.play_text}\n押すと「接続と設定」を開きます`;
}
function fillPlayOptions(templates) {
  const notes = Array.from({ length: 128 }, (_, n) => `<option value="${n}">${noteName(n)}</option>`).join('');
  const shifts = [[-24, '2オクターブ下'], [-12, '1オクターブ下'], [0, 'そのまま'], [12, '1オクターブ上'], [24, '2オクターブ上']]
    .map(([v, t]) => `<option value="${v}">${t}</option>`).join('');
  $('mapTable').innerHTML = '<tr><th>ch</th><th>使う</th><th>鍵域(下〜上)</th><th>音の高さ</th><th>ホイール</th></tr>' +
    state.channels.map(([ch, name]) => `<tr data-ch="${ch}"><td>ch${ch} ${esc(name)}</td>
      <td><input type="checkbox" class="on"></td>
      <td><span class="own"><select class="lo">${notes}</select> 〜 <select class="hi">${notes}</select></span>
          <span class="follow note">ch1 に従う</span></td>
      <td><select class="shift">${shifts}</select></td>
      <td><input type="checkbox" class="ctl" title="ピッチベンドやモジュレーションなど、ノート以外も送る"></td></tr>`).join('');
  state.templates = templates;
  $('playTpl').innerHTML = '<option value="">(選ぶと表に入ります)</option>' +
    templates.map(([k, label]) => `<option value="${k}">${esc(label)}</option>`).join('');
}
function collectPlay(mode) {
  const parts = {};
  $('mapTable').querySelectorAll('tr[data-ch]').forEach((row) => {
    parts[row.dataset.ch] = { on: row.querySelector('.on').checked, lo: +row.querySelector('.lo').value,
      hi: +row.querySelector('.hi').value, shift: +row.querySelector('.shift').value, ctl: row.querySelector('.ctl').checked };
  });
  return { mode, pair: $('playPair').value, parts };
}
async function changePlay(cfg) {
  const was = state.status && state.status.play;
  const s = await api.set_play(cfg);
  showStatus(s);
  const p = s.play;
  if (p.mode === 'map' && (!was || was.mode !== 'map'))
    toast(`外部の鍵盤を割り当て表で鳴らします: ${s.play_text}`);
  if (p.mode === 'map' && p.pair === 'poly' && state.ch <= 2) loadEditor(state.ch);   // ch2 に ch1 の音色が入った
  if (p.mode === 'map' && p.pair === 'layer' && (!was || was.pair !== 'layer'))
    toast('ch1 と ch2 で同じ音を重ねます。ch2 のデューティ比やデチューンを変えると厚みが出ます(「コピーしてずらす」も使えます)');
}
// 表やひな形を触ったら、割り当て表で鳴らすようにする
const changeMap = () => changePlay(collectPlay('map'));

// ---------- タブ ----------
function renderTabs() {
  const tabs = $('tabs');
  tabs.innerHTML = '';
  state.channels.forEach(([ch, name]) => {
    const t = document.createElement('div');
    t.className = 'tab' + (ch === state.ch ? ' on' : '');
    t.textContent = `${ch} ${name}`;
    t.onclick = () => selectChannel(ch);
    tabs.appendChild(t);
  });
}
function selectChannel(ch) {
  state.ch = ch;
  renderTabs();
  renderKeyboard();
  api.set_tab(ch).then(showStatus);
  loadEditor(ch);
  if (ch === 2 && state.status && state.status.play.mode === 'map' && state.status.play.pair === 'poly')
    toast('いまは「ch1+ch2 で2音」なので、ch1 で変えた音色は ch2 にも自動で入ります');
}

// ---------- 鍵盤 ----------
const WHITE = [0, 2, 4, 5, 7, 9, 11];
function renderKeyboard() {
  const kb = $('kb');
  const [, name, lo, hi] = state.channels.find((c) => c[0] === state.ch);
  const base = state.base[state.ch];
  kb.title = `画面の鍵盤は、開いているタブの ch${state.ch} ${name} で鳴らします(鳴る範囲: ノート ${lo}〜${hi}。薄い鍵は範囲外)`;
  kb.innerHTML = '';
  const whites = 22;
  for (let i = 0; i < whites; i++) {
    const oct = Math.floor(i / 7), n = base + oct * 12 + WHITE[i % 7];
    const w = document.createElement('div');
    w.className = 'w' + (n < lo || n > hi ? ' out' : '');
    w.dataset.note = n;
    if (n % 12 === 0) w.innerHTML = `<span>C${Math.floor(n / 12) - 1}</span>`;
    kb.appendChild(w);
    if ([0, 2, 5, 7, 9].includes(WHITE[i % 7]) && i < whites - 1) {
      const b = document.createElement('div');
      b.className = 'b' + (n + 1 < lo || n + 1 > hi ? ' out' : '');
      b.dataset.note = n + 1;
      b.style.left = `calc(${((i + 1) / whites) * 100}% - 1.6%)`;
      b.style.width = '3.2%';
      kb.appendChild(b);
    }
  }
}
let held = null;
function keyDown(e) {
  const k = e.target.closest('[data-note]');
  if (!k || k.classList.contains('out')) return;
  keyUp();
  held = k;
  k.classList.add('down');
  api.note(state.ch, +k.dataset.note, state.vel, true);
}
function keyUp() {
  if (!held) return;
  held.classList.remove('down');
  api.note(state.ch, +held.dataset.note, 0, false);
  held = null;
}

// ---------- 送信ログ ----------
const LOG_MAX = 600;
window.onLog = (lines) => {
  const log = $('log');
  const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
  const frag = document.createDocumentFragment();
  lines.forEach((line) => {
    const d = document.createElement('div');
    d.textContent = line;
    if (/ (遮断|失敗|未送信) /.test(line)) d.className = 'blocked';
    else if (/ ---- /.test(line)) d.className = 'note';
    frag.appendChild(d);
  });
  log.appendChild(frag);
  while (log.childElementCount > LOG_MAX) log.firstElementChild.remove();
  if (atEnd) log.scrollTop = log.scrollHeight;
};

// ---------- 起動 ----------
window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  const init = await api.init();
  state.channels = init.channels;
  $('offsets').innerHTML = init.offsets.map(([v, t]) =>
    `<label><input type="radio" name="offset" value="${v}"> ${t}</label>`).join('');
  $('themes').innerHTML = init.themes.map(([v, t]) =>
    `<label><input type="radio" name="theme" value="${v}"> ${t}</label>`).join('');
  fillPorts(init.ports);
  fillPlayOptions(init.templates);
  $('layerDetune').value = init.status.layer_detune;   // 選んだ値は「コピーしてずらす」で保存。ここでだけ読み込む
  showStatus(init.status);
  renderTabs();
  renderKeyboard();
  if (!init.status.out) {
    $('drawer').classList.add('open');
    toast('ふぁみみみっでぃにつながっていません。接続してください。');
  }
  loadEditor(state.ch);

  $('btnConnect').onclick = async () => {
    const r = await api.connect($('outSel').value, $('inSel').value);
    showStatus(r.status);
    if (!r.ok) toast(r.message, 'danger');
    else { toast(r.message || '接続しました'); $('drawer').classList.remove('open'); }
  };
  $('btnDisconnect').onclick = async () => showStatus(await api.disconnect());
  $('btnRefresh').onclick = async () => fillPorts(await api.ports());
  $('btnPanic').onclick = async () => { if (!(await api.panic())) toast('書き込み中のため送りませんでした'); };
  $('btnSettings').onclick = () => $('drawer').classList.toggle('open');
  $('btnCloseDrawer').onclick = () => $('drawer').classList.remove('open');
  $('btnPreset').onclick = async () => { if ($('presetSel').value) applyState(await api.preset(state.ch, $('presetSel').value)); };
  $('viewSeg').onclick = (e) => { if (e.target.dataset.v) showView(e.target.dataset.v); };
  $('btnSendAll').onclick = async () => { applyState(await api.send_all(state.ch)); toast('画面の値を全部送りました'); };
  $('btnReset').onclick = async () => applyState(await api.reset(state.ch));
  $('thru').onchange = (e) => api.set_thru(e.target.checked);
  $('playMode').onchange = () => changePlay(collectPlay(document.querySelector('#playMode input:checked').value));
  $('mapTable').onchange = changeMap;
  $('playPair').onchange = changeMap;
  $('playTpl').onchange = (e) => {
    const t = state.templates.find(([k]) => k === e.target.value);
    e.target.value = '';
    if (t) changePlay({ mode: 'map', ...t[2] });
  };
  $('playChip').onclick = () => $('drawer').classList.add('open');
  $('btnLayerCopy').onclick = async () => {
    const st2 = await api.layer_copy(+$('layerDetune').value);
    if (state.ch === 2) applyState(st2);
    toast(`ch1 の音色を ch2 にコピーして、ch2 の音程を「${$('layerDetune').selectedOptions[0].text}」ずらしました`);
  };
  $('offsets').onchange = (e) => api.set_offset(+e.target.value);
  $('themes').onchange = (e) => { document.documentElement.dataset.theme = e.target.value; api.set_theme(e.target.value); };
  $('btnCopyLog').onclick = () => navigator.clipboard.writeText($('log').innerText).then(() => toast('ログをコピーしました'));
  $('btnLogDir').onclick = () => api.open_log_dir();
  $('btnClearLog').onclick = () => ($('log').innerHTML = '');
  $('velRange').oninput = (e) => { state.vel = +e.target.value; $('velNum').textContent = state.vel; };
  $('octDown').onclick = () => { state.base[state.ch] = Math.max(0, state.base[state.ch] - 12); renderKeyboard(); };
  $('octUp').onclick = () => { state.base[state.ch] = Math.min(96, state.base[state.ch] + 12); renderKeyboard(); };
  const kb = $('kb');
  kb.addEventListener('pointerdown', (e) => { kb.setPointerCapture(e.pointerId); keyDown(e); });
  kb.addEventListener('pointerup', keyUp);
  kb.addEventListener('pointercancel', keyUp);
  showStatus(await api.set_tab(state.ch));
});
