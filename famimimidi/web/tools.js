// 波形メモリ・A/B 比較・MIDI 書き出し・試聴フレーズ・ライブラリのバックアップ(C4a)
'use strict';

const openPage = (id) => $(id).classList.add('open');
const closePage = (id) => $(id).classList.remove('open');

// ---------- 試聴フレーズ(下の鍵盤の横) ----------
async function setupPhrases() {
  const names = await api.phrases();
  for (const id of ['phraseSel', 'abPhrase']) {
    const sel = $(id);
    sel.innerHTML = '';
    names.forEach((n) => sel.add(new Option(n, n)));
  }
  $('btnPhrase').onclick = () => api.play_phrase(state.ch, $('phraseSel').value, state.base[state.ch], state.vel);
  $('btnPhraseStop').onclick = () => api.stop_phrase();
}

// ---------- 波形メモリ ----------
const wv = { samples: [0, 2, 4, 6, 8, 10, 12, 14, 15, 13, 11, 9, 7, 5, 3, 1], presets: {}, slots: [] };
const CELL = 24;

function drawWave() {
  const svg = $('waveSvg');
  let h = '';
  for (let i = 1; i < 16; i++) h += `<line x1="0" y1="${i * CELL}" x2="384" y2="${i * CELL}"/>`;
  wv.samples.forEach((v, i) => {
    const y = (15 - v) * CELL;
    h += `<rect class="wbar" x="${i * CELL + 2}" y="${y}" width="${CELL - 4}" height="${384 - y}"/>`;
    h += `<rect class="wtop" x="${i * CELL + 2}" y="${y}" width="${CELL - 4}" height="${CELL}"/>`;
  });
  svg.innerHTML = h;
  $('waveVals').textContent = '値: ' + wv.samples.map((v) => v.toString(16).toUpperCase()).join(' ');
}
function waveAt(e) {
  const svg = $('waveSvg');
  const pt = svg.createSVGPoint();
  pt.x = e.clientX;
  pt.y = e.clientY;
  const { x, y } = pt.matrixTransform(svg.getScreenCTM().inverse());
  const col = Math.max(0, Math.min(15, Math.floor(x / CELL)));
  const val = Math.max(0, Math.min(15, 15 - Math.floor(y / CELL)));
  if (wv.samples[col] !== val) { wv.samples[col] = val; drawWave(); }
}
async function refreshWave() {
  const s = await api.wave_state();
  wv.presets = s.presets;
  wv.slots = s.slots;
  const box = $('wavePresets');
  box.innerHTML = '';
  Object.entries(s.presets).forEach(([name, samples]) => {
    const b = document.createElement('button');
    b.className = 'btn';
    b.textContent = name;
    b.onclick = () => { wv.samples = [...samples]; $('waveName').value = name.replace(/(無音)|\s/g, ''); drawWave(); };
    box.appendChild(b);
  });
  const sel = $('waveSlot');
  const cur = sel.value;
  sel.innerHTML = '';
  s.slots.forEach((x) => sel.add(new Option(`PC${x.pc}(送信値${x.pc - 1}): ${x.name || '(このソフトでは未登録)'}`, x.pc)));
  if (cur) sel.value = cur;
}
function setupWave() {
  const svg = $('waveSvg');
  let down = false;
  svg.addEventListener('pointerdown', (e) => { down = true; svg.setPointerCapture(e.pointerId); waveAt(e); });
  svg.addEventListener('pointermove', (e) => { if (down) waveAt(e); });
  svg.addEventListener('pointerup', () => (down = false));
  $('btnWave').onclick = async () => { await refreshWave(); drawWave(); openPage('wavePage'); };
  $('wavePlay').onclick = async () => { if (!(await api.wave_preview(wv.samples, +$('wavePitch').value))) toast('鳴らせませんでした(書き込み中?)'); };
  $('waveDrum').onclick = () => api.wave_drum();
  $('waveRecall').onclick = () => api.wave_recall(+$('waveSlot').value, +$('wavePitch').value);
  $('waveLoad').onclick = async () => {
    const w = await api.wave_load(+$('waveSlot').value);
    if (!w) { toast('このソフトで登録した記録がないので、読み込めません'); return; }
    wv.samples = [...w.samples];
    $('waveName').value = w.name;
    drawWave();
  };
  $('waveReg').onclick = () => runPlan('wave', +$('waveSlot').value, { samples: wv.samples, name: $('waveName').value });
}

// ---------- A/B 比較 ----------
const ab = { timers: [] };
function fillLibSelect(sel, withNone = false) {
  const cur = sel.value;
  sel.innerHTML = '';
  if (withNone) sel.add(new Option('(なし)', ''));
  lib.list.forEach((p) => sel.add(new Option(`${p.name}(ch${p.channel})`, p.id)));
  if (cur) sel.value = cur;
}
async function refreshAB() {
  const r = $('abA').value && $('abB').value ? await api.ab_diff($('abA').value, $('abB').value) : null;
  const body = $('abRows');
  body.innerHTML = '';
  $('abNote').textContent = r && !r.same_ch ? `※ A は ch${r.a_ch}用、B は ch${r.b_ch}用です。違いは A のチャンネルで比べています。` : '';
  if (!r) return;
  if (!r.rows.length) body.innerHTML = '<tr><td colspan="3">(違いはありません)</td></tr>';
  r.rows.forEach((x) => body.insertAdjacentHTML('beforeend',
    `<tr class="${x.audible ? '' : 'mute'}"><td>${esc(x.name)}</td><td>${esc(x.a)}</td><td>${esc(x.b)}</td></tr>`));
}
async function abPlay(key) {
  const id = $(key === 'A' ? 'abA' : 'abB').value;
  if (!id) return null;
  const r = await api.ab_play(id, $('abPhrase').value);
  if (!r) { toast('鳴らせませんでした(書き込み中?)'); return null; }
  $('abNow').textContent = `いま: ${key}`;
  $('abNow').className = 'abnow ' + (key === 'A' ? 'abA' : 'abB');
  if (state.ch !== r.ch) selectChannel(r.ch);
  return r;
}
function abStop() {
  ab.timers.forEach(clearTimeout);
  ab.timers = [];
  api.stop_phrase();
  $('abNow').textContent = '';
}
function setupAB() {
  $('btnAB').onclick = () => {
    fillLibSelect($('abA'));
    fillLibSelect($('abB'));
    if (lib.sel && !$('abA').dataset.set) { $('abA').value = lib.sel; $('abA').dataset.set = 1; }
    refreshAB();
    openPage('abPage');
  };
  $('abA').onchange = refreshAB;
  $('abB').onchange = refreshAB;
  $('abPlayA').onclick = () => { abStop(); abPlay('A'); };
  $('abPlayB').onclick = () => { abStop(); abPlay('B'); };
  $('abStop').onclick = abStop;
  $('abAlt').onclick = () => {
    abStop();
    const seq = ['A', 'B', 'A', 'B'];
    const step = async (i) => {
      if (i >= seq.length) { $('abNow').textContent = ''; return; }
      const r = await abPlay(seq[i]);
      if (!r) return;
      ab.timers.push(setTimeout(() => step(i + 1), 150 + r.ms + 600));
    };
    step(0);
  };
}

// ---------- MIDI 書き出し ----------
async function setupExport() {
  const modes = await api.export_modes();
  $('exportModes').innerHTML = modes.map(([k, t], i) =>
    `<label class="check" style="display:block"><input type="radio" name="emode" value="${k}" ${i === 0 ? 'checked' : ''}> ${esc(t)}</label>`).join('');
  $('btnExport').onclick = () => {
    $('exportRows').innerHTML = state.channels.map(([ch, name]) =>
      `<div class="field2"><label>ch${ch} ${esc(name)}</label><select data-ech="${ch}"></select></div>`).join('');
    $('exportRows').querySelectorAll('select').forEach((s) => fillLibSelect(s, true));
    const p = lib.list.find((x) => x.id === lib.sel);
    if (p) $('exportRows').querySelector(`[data-ech="${p.channel}"]`).value = p.id;
    openPage('exportPage');
  };
  $('exportGo').onclick = async () => {
    const assign = {};
    $('exportRows').querySelectorAll('select').forEach((s) => { if (s.value) assign[s.dataset.ech] = s.value; });
    const mode = document.querySelector('input[name=emode]:checked').value;
    const r = await api.export_midi(assign, mode);
    if (r.cancel) return;
    if (r.error) { toast(r.error); return; }
    closePage('exportPage');
    await info('書き出しました', r.path + (r.notes.length ? '\n\n' + r.notes.join('\n') : ''));
  };
}

// ---------- 起動時の配線 ----------
window.addEventListener('pywebviewready', async () => {
  document.querySelectorAll('[data-close]').forEach((x) => (x.onclick = () => { abStop(); closePage(x.dataset.close); }));
  await setupPhrases();
  setupWave();
  setupAB();
  await setupExport();
  $('libBackup').onclick = async () => {
    const r = await api.lib_backup();
    if (r.path) toast('書き出しました: ' + r.path);
  };
  $('libRestore').onclick = async () => {
    const r = await api.lib_restore();
    if (r.error) toast(r.error, 'danger');
    else if (!r.cancel) { await refreshLib(); await refreshSets(); toast(`音色 ${r.count} 個、演奏セット ${r.sets} 個を取り込みました`); }
  };
});
