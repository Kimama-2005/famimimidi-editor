// コードで弾く(「♪ 演奏セット」タブ、SPEC_v2 7.2)。コードの計算・配置・鳴らし方は Python(performance/chordmode.py)。
'use strict';

const cm = { view: null, loading: false };
const STYLE_DEFS = [
  ['piano', 'ピアノ', '下からストラム・毎回打鍵', 'M8 26V18M20 26V12M32 26V6'],
  ['organ', 'オルガン', '同時発音・レガート', 'M8 26V6M20 26V6M32 26V6'],
  ['strum', 'ギター', '上から速いストラム', 'M8 26V6M20 26V12M32 26V18'],
  ['pad', 'パッド', 'スロー アタック/リリース', 'M4 26Q30 4 76 10'],
];
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/** play.js の renderPlay の後に、app.js の applyState から呼ばれる */
const _renderPlay = window.renderPlay;
window.renderPlay = (st) => {
  _renderPlay(st);
  if (st.place === 'play' && st.session.chord_active) loadChord();
};

async function loadChord() {
  if (cm.loading) return;
  cm.loading = true;
  try { showChordView(await api.chord_view()); } finally { cm.loading = false; }
}

function showChordView(v) {
  if (!v || v.error) { if (v && v.error) toast(v.error, 'danger'); return; }
  if (v.view) v = v.view;
  if (v.keyboard && S.state) { S.state.keyboard = v.keyboard; renderKb(S.state); }   // 下の鍵盤のコード名
  cm.view = v;
  const st = v.state, set = v.settings;
  // 曲
  $('songList').innerHTML = v.songs.map((s, i) =>
    `<li data-i="${i}" class="${i === st.song ? 'sel cur' : ''} ${s.empty ? 'empty' : ''}">${i + 1}. ${esc(s.name || (s.empty ? '(空き)' : '(名前なし)'))}</li>`).join('');
  // 配置
  $('layoutSeg').innerHTML = v.layouts.map(([k, n]) => `<button data-v="${k}" class="${k === set.layout ? 'on' : ''}">${esc(n.replace('曲の', ''))}</button>`).join('');
  // コードの表(上から 3段目・2段目・1段目・4段目)
  $('chordGrid').innerHTML = v.rows.map((r) => `<div class="rowh">${esc(r.title)}</div>` + r.cells.map((c, off) =>
    `<div class="cell ${[1, 3, 6, 8, 10].includes(off) ? 'black' : ''} ${c.name ? '' : 'none'} ${c.mod ? 'mod' : ''}" data-row="${r.row}" data-off="${off}" data-n="${c.note}"${c.tip ? ` title="${esc(c.tip)}"` : ''}>`
    + `${esc(c.name) || '&nbsp;'}<small>${NOTE_NAMES[off]}</small></div>`).join('')).join('');
  // 進行
  // 行ごとの譜面。ChordWiki から取り込んだ曲は歌詞つき(歌詞は保存していない。表示するときだけページから読む)
  const sheet = v.sheet || [];
  $('chordProg').classList.toggle('sheet', sheet.length > 0);
  $('chordProg').innerHTML = sheet.length
    ? sheet.map((ln) => (ln.kind === 'comment'
      ? `<div class="sheethead">${esc(ln.text)}</div>`
      : `<div class="sheetline">${ln.segs.map(sheetSeg).join('')}</div>`)).join('')
      + (v.sheet_note ? `<div class="note">${esc(v.sheet_note)}</div>` : '')
    : '<span class="none">(この曲にはまだコードがありません。「曲を編集・取り込み…」から入れます)</span>';
  const warn = [];
  if (st.overflow.length) warn.push(`鍵盤に入りきらないコード: ${st.overflow.join(' ')}`);
  if (st.errors.length) warn.push(`読めないコード名: ${st.errors.map((e) => e.split(': ').pop()).join(' ')}`);
  $('chordWarn').textContent = warn.join(' / ');
  // ボイシング
  document.querySelectorAll('#methodSeg button').forEach((b) => b.classList.toggle('on', b.dataset.v === set.method));
  const arp = set.method === 'arp';
  $('methodHint').textContent = arp ? 'ch1 で和音をアルペジオ、ch3 はベース' : 'ベース+3声';
  $('voices').innerHTML =
    `<div class="voice" style="border-color:var(--c3)"><h3>ベース ― 3 三角波</h3><span class="note">音域 </span>`
    + `<span class="seg" id="bassSeg"><button data-v="low" class="${set.bass === 'low' ? 'on' : ''}">C2〜</button><button data-v="mid" class="${set.bass === 'mid' ? 'on' : ''}">C3〜</button></span></div>`
    + `<div class="voice" style="border-color:var(--c1)"><h3>${arp ? '和音(アルペジオ)' : 'ボイス1'} ― 1 パルス</h3>`
    + `<label class="check"><input type="checkbox" id="glide" ${set.glide ? 'checked' : ''}> グライド</label>`
    + '<span class="help" data-tip="コードを変えるとき、音程をすべらせる(ふぁみみみっでぃのポルタメント。ch1〜3 に効きます)。すべらせるため、打ち直しはしません">?</span></div>'
    + `<div class="voice ${arp ? 'dim' : ''}" style="border-color:var(--c2)"><h3>ボイス2 ― 2 パルス</h3><span class="hint2">ボイス1 とともに 3rd・7th を優先</span></div>`
    + `<div class="voice ${arp ? 'dim' : ''}" style="border-color:var(--c5)"><h3>ボイス3 ― 5 波形</h3><span class="hint2">波形メモリに切り替えて鳴らします</span></div>`;
  // 奏法プリセット
  $('styles').innerHTML = STYLE_DEFS.map(([k, n, sub, d]) =>
    `<div class="style ${k === set.style ? 'on' : ''}" data-v="${k}"><svg viewBox="0 0 80 30"><path d="${d}"/></svg>${n}<small>${sub}</small></div>`).join('');
  if (document.activeElement !== $('spread')) { $('spread').value = set.spread; $('spreadNum').textContent = `${set.spread}ms`; }
  onChordState(st);
}

/** 譜面の1つのます。コードの頭(コード+その下の最初の数文字)のあとの歌詞は1文字(英単語は単語)ずつに分け、
 *  行の途中のどこでも折り返せるようにする */
function sheetSeg(sg) {
  if (sg.bar) return '<b class="bar">|</b>';
  const parts = (sg.lyric || '').match(/[A-Za-z0-9'’,.!?]+\s*|\s+|./gu) || [];
  const chord = sg.chord || '';
  const headLen = chord ? Math.max(1, Math.ceil(chord.length / 2)) : (parts.length ? 1 : 0);   // 全角1文字 ≒ 半角2文字
  const head = parts.slice(0, headLen).join(''), rest = parts.slice(headLen);
  const attr = sg.ci != null ? ` data-i="${sg.ci}" title="押すと、ここから弾きます"` : '';
  return `<span class="seg${chord ? '' : ' plain'}"${attr}><i>${esc(chord)}</i><u>${esc(head)}</u></span>`
    + rest.map((t) => `<span class="seg plain tail"><i></i><u>${esc(t)}</u></span>`).join('');
}

/** Python からの知らせ(コード・曲・キー・ホールド・ON/OFF が変わった) */
window.onChordState = (st) => {
  if (!cm.view) return;
  const songChanged = st.song !== cm.view.state.song || st.key !== cm.view.state.key;
  cm.view.state = st;
  if (songChanged) { loadChord(); return; }
  $('chordNow').textContent = st.chord ? st.chord.name : '―';
  $('chordNext').textContent = st.next ? st.next.name + (st.next.how ? `(${st.next.how}${st.next.exact === false ? '・ベースは違う' : ''})` : '') : '―';
  $('keyName').textContent = st.key_name + (st.key !== st.song_key ? '(移調)' : '');
  $('btnHold').classList.toggle('on', st.latch);
  document.querySelectorAll('#chordGrid .cell').forEach((c) => {
    c.classList.toggle('cur', !!st.chord && +c.dataset.row === st.chord.row && +c.dataset.off === st.chord.off);
    c.classList.toggle('next', !!st.next && (st.next.cells || []).some(([r, o]) => +c.dataset.row === r && +c.dataset.off === o));
  });
  document.querySelectorAll('#chordProg span[data-i]').forEach((s) => {
    s.classList.toggle('cur', +s.dataset.i === st.prog_pos);
    s.classList.toggle('next', !!st.next && +s.dataset.i === st.next.index);
  });
  const now = $('chordProg').querySelector('span.cur') || $('chordProg').querySelector('span.next');
  if (now && $('chordProg').classList.contains('sheet')) {
    // 譜面の中だけ、コードが変わるたびに少しずつなめらかに送る(いまの行が欄の上から 3分の1 あたりに来るように)。
    // 前は欄の外に出た瞬間に大きく飛んでいた
    const box = $('chordProg'), r = now.getBoundingClientRect(), b = box.getBoundingClientRect();
    const want = Math.max(0, Math.min(box.scrollHeight - box.clientHeight, box.scrollTop + r.top - b.top - b.height / 3));
    if (Math.abs(want - box.scrollTop) > 2) box.scrollTo({ top: want, behavior: 'smooth' });
  }
  // 下の鍵盤: いまのコードは緑、次に弾く鍵が光る
  const onPlay = !S.state || S.state.place === 'play';       // 1〜5 のタブの画面の鍵盤はその ch だけなので光らせない
  document.querySelectorAll('#kb [data-n]').forEach((k) => {
    k.classList.toggle('cur', onPlay && !!st.chord && +k.dataset.n === st.chord.note);
    k.classList.toggle('next', onPlay && !!st.next && (st.next.notes || []).includes(+k.dataset.n));
  });
};

// ---------------------------------------------------------------- 曲の編集
function openSongEditor() {
  const v = cm.view;
  if (!v) return;
  $('songSel').innerHTML = v.book.songs.map((s, i) => `<option value="${i}">${i + 1}. ${esc(s.name || '(空き)')}</option>`).join('');
  $('songSel').value = v.state.song;
  $('songKey').innerHTML = '<option value="auto">自動(コードから推定)</option>'
    + NOTE_NAMES.map((n, i) => `<option value="${i}">${n}</option>`).join('');
  fillSong(v.state.song);
  const common = v.book.common_row || ['C/E', 'C#dim7', 'G/B', 'F/G', 'Csus4', 'Fadd9', 'Fm6', 'Gsus4', 'C/G', 'G7sus4', 'Bb/C', 'Cadd9'];
  $('commonRow').innerHTML = common.map((c, i) => `<input type="text" data-i="${i}" value="${esc(c)}" placeholder="${NOTE_NAMES[i]}">`).join('');
  openOv('ovSong');
}
function fillSong(i) {
  const s = cm.view.book.songs[i];
  $('songName').value = s.name;
  $('songKey').value = s.key === null ? 'auto' : String(s.key);
  $('songText').value = s.text;
  $('songErr').textContent = '';
}

// ---------------------------------------------------------------- 操作
window.addEventListener('pywebviewready', () => {
  $('songList').onclick = async (e) => { const li = e.target.closest('li[data-i]'); if (li) showChordView(await api.chord_song(+li.dataset.i)); };
  $('layoutSeg').onclick = async (e) => { const b = e.target.closest('button'); if (b) showChordView(await api.set_chord_settings({ layout: b.dataset.v })); };
  $('methodSeg').onclick = async (e) => { const b = e.target.closest('button'); if (b) showChordView(await api.set_chord_settings({ method: b.dataset.v })); };
  $('voices').onclick = async (e) => {
    const b = e.target.closest('#bassSeg button');
    if (b) showChordView(await api.set_chord_settings({ bass: b.dataset.v }));
  };
  $('voices').onchange = async (e) => { if (e.target.id === 'glide') showChordView(await api.set_chord_settings({ glide: e.target.checked })); };
  $('styles').onclick = async (e) => { const d = e.target.closest('.style'); if (d) showChordView(await api.set_chord_settings({ style: d.dataset.v })); };
  $('spread').oninput = () => {
    $('spreadNum').textContent = `${$('spread').value}ms`;
    clearTimeout(cm.spreadTimer);
    cm.spreadTimer = setTimeout(async () => showChordView(await api.set_chord_settings({ spread: +$('spread').value })), 150);
  };
  $('keyDown').onclick = async () => showChordView(await api.chord_key(null, -1));
  $('keyUp').onclick = async () => showChordView(await api.chord_key(null, 1));
  $('keyName').onclick = async () => cm.view && showChordView(await api.chord_key(cm.view.state.song_key, null));
  $('btnHold').onclick = () => api.chord_hold();
  $('chordProg').onclick = (e) => { const sp = e.target.closest('span[data-i]'); if (sp) api.chord_set_next(+sp.dataset.i); };
  $('btnStop').onclick = () => api.chord_stop();
  const grid = $('chordGrid');
  let held = null;
  grid.addEventListener('pointerdown', (e) => {
    const c = e.target.closest('.cell:not(.none)');
    if (!c) return;
    held = c;
    try { grid.setPointerCapture(e.pointerId); } catch (_) { /* */ }
    api.chord_play(+c.dataset.row, +c.dataset.off, true, S.vel);
  });
  const up = () => { if (held) api.chord_play(+held.dataset.row, +held.dataset.off, false, 0); held = null; };
  grid.addEventListener('pointerup', up);
  grid.addEventListener('pointercancel', up);
  $('btnSongEdit').onclick = openSongEditor;
  $('songSel').onchange = () => fillSong(+$('songSel').value);
  $('btnSongSave').onclick = async () => {
    const i = +$('songSel').value;
    const r = await api.save_song(i, $('songName').value, $('songKey').value, $('songText').value);
    showChordView(r.view);
    await api.chord_song(i).then(showChordView);
    $('songErr').textContent = r.errors.length ? `読めないコード名: ${r.errors.map((e) => e.split(': ').pop()).join(' ')}` : '保存しました';
  };
  $('btnWiki').onclick = async () => {
    const i = +$('songSel').value;
    const r = await api.import_chordwiki(i);
    if (!r) return;
    if (r.error) { toast(r.error, 'danger'); return; }
    showChordView(r.view);
    fillSong(i);
    $('songErr').textContent = r.unread && r.unread.length ? `取り込めなかったコード名: ${r.unread.join(' ')}` : 'ChordWiki から取り込みました(歌詞は取り込んでいません)';
  };
  $('btnCommonSave').onclick = async () => {
    const row = [...document.querySelectorAll('#commonRow input')].map((x) => x.value);
    const r = await api.save_common(row);
    if (r.error) { toast(r.error, 'danger'); return; }
    showChordView(r.view);
    toast('全曲共通のコードを保存しました');
  };
  $('btnBookImport').onclick = async () => {
    if (!(await ask({ title: 'コードセットを取り込む', text: '12曲まるごと、選んだファイルの曲に置き換わります。', ok: '選ぶ' }))) return;
    const r = await api.import_chordbook();
    if (!r) return;
    if (r.error) { toast(r.error, 'danger'); return; }
    showChordView(r.view);
    openSongEditor();
    toast('コードセットを取り込みました');
  };
  $('btnBookExport').onclick = async () => { const r = await api.export_chordbook(); if (r && r.path) toast(`書き出しました: ${r.path}`); };
  // パソコンのキー(文字入力中・小窓を開いているときは除く)
  document.addEventListener('keydown', async (e) => {
    if (e.target.matches('input[type=text], textarea, select') || document.querySelector('.overlay.open')) return;
    if (!S.state || S.state.place !== 'play' || !S.state.session.chord_active) return;
    const k = e.key;
    if (k === 'ArrowLeft' || k === 'ArrowRight') { e.preventDefault(); showChordView(await api.chord_next_song(k === 'ArrowLeft' ? -1 : 1)); }
    else if (k === 'ArrowUp' || k === 'ArrowDown') { e.preventDefault(); showChordView(await api.chord_key(null, k === 'ArrowUp' ? 1 : -1)); }
    else if (k === 'h' || k === 'H') api.chord_hold();
    else if (k === 'Escape') api.chord_stop();
  });
});
