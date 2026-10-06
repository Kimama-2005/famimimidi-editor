// ライブラリ、カートリッジ(保存場所)、確認ダイアログ、書き込み中の警告(C3)
'use strict';

const lib = { list: [], sets: [], sel: null, ssel: null, filter: '', kind: 'patch' };
const cart = { view: null, sel: 89 };
const CATS = ['lead', 'backing', 'bass', 'drums', 'fx', 'other'];

// ---------- ダイアログ ----------
function openModal(html) {
  $('modalBox').innerHTML = html;
  $('modal').classList.add('open');
  return $('modalBox');
}
function closeModal() { $('modal').classList.remove('open'); }

function ask(title, message, okText = 'はい', danger = false) {
  return new Promise((resolve) => {
    const box = openModal(`<h2>${esc(title)}</h2><div style="white-space:pre-line">${esc(message)}</div>
      <div class="btns"><button class="btn" id="mNo">やめる</button><button class="btn ${danger ? 'danger' : 'main'}" id="mYes">${esc(okText)}</button></div>`);
    box.querySelector('#mYes').onclick = () => { closeModal(); resolve(true); };
    box.querySelector('#mNo').onclick = () => { closeModal(); resolve(false); };
  });
}

function info(title, message) {
  return new Promise((resolve) => {
    const box = openModal(`<h2>${esc(title)}</h2><div style="white-space:pre-line">${esc(message)}</div>
      <div class="btns"><button class="btn main" id="mOk">OK</button></div>`);
    box.querySelector('#mOk').onclick = () => { closeModal(); resolve(); };
  });
}

function setForm(title, p = {}) {
  return new Promise((resolve) => {
    const box = openModal(`<h2>${esc(title)}</h2>
      <div class="note" style="margin-bottom:6px">いまの 5 つの ch の音色と、鍵盤の割り当て表をまとめて保存します。</div>
      <div class="field"><label>名前</label><input type="text" id="fName" value="${esc(p.name || '')}"></div>
      <div class="field"><label>メモ</label><textarea id="fNotes" rows="4">${esc(p.notes || '')}</textarea></div>
      <div class="btns"><button class="btn" id="mNo">やめる</button><button class="btn main" id="mYes">OK</button></div>`);
    box.querySelector('#fName').focus();
    box.querySelector('#mYes').onclick = () => {
      const name = box.querySelector('#fName').value.trim();
      if (!name) { toast('名前を入れてください'); return; }
      closeModal();
      resolve({ name, notes: box.querySelector('#fNotes').value });
    };
    box.querySelector('#mNo').onclick = () => { closeModal(); resolve(null); };
  });
}

function patchForm(title, p = {}) {
  return new Promise((resolve) => {
    const box = openModal(`<h2>${esc(title)}</h2>
      <div class="field"><label>名前</label><input type="text" id="fName" value="${esc(p.name || '')}"></div>
      <div class="field"><label>分類</label><select id="fCat">${CATS.map((c) => `<option ${c === (p.category || 'other') ? 'selected' : ''}>${c}</option>`).join('')}</select></div>
      <div class="field"><label>メモ</label><textarea id="fNotes" rows="4">${esc(p.notes || '')}</textarea></div>
      <div class="btns"><button class="btn" id="mNo">やめる</button><button class="btn main" id="mYes">OK</button></div>`);
    box.querySelector('#fName').focus();
    box.querySelector('#mYes').onclick = () => {
      const name = box.querySelector('#fName').value.trim();
      if (!name) { toast('名前を入れてください'); return; }
      closeModal();
      resolve({ name, category: box.querySelector('#fCat').value, notes: box.querySelector('#fNotes').value });
    };
    box.querySelector('#mNo').onclick = () => { closeModal(); resolve(null); };
  });
}

// カートリッジへの書き込みの確認。「元に戻せない」ことへのチェックがないと進めない
function confirmWrite(p) {
  return new Promise((resolve) => {
    const lines = p.lines.map((l) => `<div class="${l.startsWith('※') ? 'warn' : ''}">${esc(l)}</div>`).join('');
    const box = openModal(`<h2>${esc(p.title)}</h2><div class="lines">${lines}</div>
      <div class="dangertext" style="margin-top:8px">保存には約${p.secs}秒かかります。その間はファミコンの電源を切らないでください。</div>
      <label class="check" style="display:block;margin-top:10px"><input type="checkbox" id="mAgree"> 元に戻せないことを分かったうえで進める</label>
      <pre id="mDetail">${esc(p.detail)}</pre>
      <div class="btns"><button class="btn" id="mDet">くわしい送信内容</button><span class="spacer"></span>
        <button class="btn" id="mNo">やめる</button><button class="btn main" id="mYes" disabled>${esc(p.ok_text)}</button></div>`);
    const yes = box.querySelector('#mYes');
    box.querySelector('#mAgree').onchange = (e) => (yes.disabled = !e.target.checked);
    box.querySelector('#mDet').onclick = () => box.querySelector('#mDetail').classList.toggle('open');
    yes.onclick = () => { closeModal(); resolve(true); };
    box.querySelector('#mNo').onclick = () => { closeModal(); resolve(false); };
  });
}

// ---------- 書き込み ----------
let writeTimer = null;
async function runPlan(kind, a = null, b = null) {
  const p = await api.cart_plan(kind, a, b);
  if (p.error) { await info('できません', p.error); return; }
  if (!(await confirmWrite(p))) return;
  const r = await api.cart_run(p.token);
  if (r.error) { await info('書き込みを始められません', r.error); return; }
  // 前回の 100% が残っていると、そこから戻って見えるので、動きを付けずに 0% にしてから始める
  const bar = $('writeBar');
  bar.style.transition = 'none';
  bar.style.width = '0%';
  void bar.offsetWidth;
  bar.style.transition = '';
  $('writeLeft').textContent = '';
  $('writeStep').textContent = '';
  $('writing').classList.add('open');
  const t0 = Date.now(), total = Math.max(r.secs, 1) * 1000;
  clearInterval(writeTimer);
  writeTimer = setInterval(() => {
    const raw = Date.now() - t0, e = Math.min(raw, total);
    $('writeBar').style.width = `${(e / total) * 100}%`;
    if (raw < total + 3000) $('writeLeft').textContent = `あと約 ${Math.ceil((total - e) / 1000)} 秒`;
    else if (raw < total + 20000) $('writeLeft').textContent = '仕上げ中…';
    else $('writeLeft').textContent = '応答がありません。ファミコンの電源を入れ直し、このソフトを ✕ で閉じて開き直してください。' +
      '(この場所の中身は「不明」として扱ってください)';
  }, 200);
}
window.onWriteProgress = (i, n, text) => { $('writeStep').textContent = `${i}/${n}  ${text}`; };
window.onWriteDone = async (ok, message) => {
  clearInterval(writeTimer);
  $('writing').classList.remove('open');
  await refreshCart();
  if ($('wavePage').classList.contains('open')) await refreshWave();
  if (ok) ex.plan = {};                    // まとめて割り当ての予定は、成功したら消す
  await refreshExpert();
  await info(ok ? '完了しました' : '書き込みに失敗しました', message);
};

// ---------- ライブラリ ----------
async function refreshLib(selectId) {
  lib.list = await api.lib_list();
  if (selectId !== undefined) lib.sel = selectId;
  renderLib();
}
async function refreshSets(selectId) {
  lib.sets = await api.set_list();
  if (selectId !== undefined) lib.ssel = selectId;
  renderLib();
}
function showKind(kind) {
  lib.kind = kind;
  $('libKind').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.k === kind));
  $('libCart').style.display = kind === 'set' ? 'none' : '';
  renderLib();
}
function renderSets() {
  const ul = $('libList');
  const f = lib.filter.toLowerCase();
  ul.innerHTML = '';
  lib.sets.filter((d) => !f || d.name.toLowerCase().includes(f)).forEach((d) => {
    const li = document.createElement('li');
    li.className = (d.id === lib.ssel ? 'sel' : '') + (d.current ? ' cur' : '');
    li.innerHTML = `${esc(d.name)}${d.current ? ' <small>使用中</small>' : ''}`;
    li.title = d.summary;
    li.onclick = () => { lib.ssel = d.id; renderLib(); };
    li.ondblclick = () => loadSelected();
    ul.appendChild(li);
  });
  if (!lib.sets.length) ul.innerHTML = '<li class="note">(まだありません。「新規保存…」で、いまの 5ch の音色と割り当て表を保存できます)</li>';
  showSetInfo();
}
async function showSetInfo() {
  const box = $('libInfo');
  const d = lib.ssel && (await api.set_info(lib.ssel));
  if (!d) { box.textContent = ''; return; }
  box.textContent = `${d.name}\n割り当て: ${d.summary}\n` +
    d.parts.map((p) => `・ch${p.ch}${p.used ? '' : '(鍵盤では使わない)'}: ${p.name}`).join('\n') + (d.notes ? `\n\n${d.notes}` : '');
}
function renderLib() {
  if (lib.kind === 'set') { renderSets(); return; }
  const ul = $('libList');
  const f = lib.filter.toLowerCase();
  ul.innerHTML = '';
  lib.list.filter((p) => !f || p.name.toLowerCase().includes(f) || p.category.includes(f)).forEach((p) => {
    const li = document.createElement('li');
    li.className = p.id === lib.sel ? 'sel' : '';
    li.innerHTML = `${esc(p.name)} <small>ch${p.channel}</small>`;
    li.onclick = () => { lib.sel = p.id; renderLib(); showInfo(); };
    li.ondblclick = () => loadSelected();
    ul.appendChild(li);
  });
  showInfo();
}
async function showInfo() {
  const box = $('libInfo');
  if (!lib.sel) { box.textContent = ''; return; }
  const p = await api.lib_info(lib.sel);
  if (!p) { box.textContent = ''; return; }
  box.textContent = `${p.name}(ch${p.channel} / ${p.category})\n` + p.cc.map(([n, v]) => `・${n} = ${v}`).join('\n') +
    (p.notes ? `\n\n${p.notes}` : '');
}
async function loadSelected() {
  if (lib.kind === 'set') {
    if (!lib.ssel) { toast('一覧から演奏セットを選んでください'); return; }
    const r = await api.set_load(lib.ssel);
    if (r.error) { toast(r.error); return; }
    showStatus(r.status);
    await refreshSets();
    loadEditor(state.ch);
    toast('演奏セットを読み込みました(5ch の音色を送り、鍵盤を割り当て表で鳴らします)');
    return;
  }
  if (!lib.sel) { toast('一覧から音色を選んでください'); return; }
  const r = await api.lib_load(lib.sel);
  if (r) { selectChannel(r.ch); toast('読み込んで送りました'); }
}

// ---------- カートリッジ画面 ----------
async function openCart() {
  $('cartPage').classList.add('open');
  await refreshCart();
}
async function refreshCart() {
  cart.view = await api.cart_view();
  renderTiles();
  renderPlace();
  renderRows();
}
function renderTiles() {
  const box = $('tiles');
  box.innerHTML = '';
  cart.view.places.forEach((p) => {
    const t = document.createElement('div');
    t.className = 'tile' + (p.empty ? '' : ' filled') + (p.pc === cart.sel ? ' sel' : '');
    t.innerHTML = `<b>場所${p.place}・${p.pc}</b>${esc(p.empty ? '(空き)' : p.name)}`;
    t.title = `場所 ${p.place}(呼び出し番号 ${p.pc}): ${p.name}`;
    t.onclick = () => { cart.sel = p.pc; renderTiles(); renderPlace(); };
    box.appendChild(t);
  });
}
function renderPlace() {
  const p = cart.view.places.find((x) => x.pc === cart.sel);
  $('placeHead').textContent = `場所 ${p.place}(呼び出し番号 ${p.pc})`;
  $('placeName').textContent = `入っている音色: ${p.name}`;
  $('tryCh').innerHTML = [1, 2, 3, 4, 5].map((c) => `<option ${c === (p.channel || state.ch) ? 'selected' : ''}>${c}</option>`).join('');
  const sel = $('putSel');
  sel.innerHTML = '';
  lib.list.forEach((x) => sel.add(new Option(`${x.name}(ch${x.channel}用)`, x.id)));
  if (lib.sel) sel.value = lib.sel;
}
function renderRows() {
  const filled = cart.view.places.filter((p) => !p.empty);
  const opts = filled.map((p) => `<option value="${p.pc}">場所${p.place}(${p.pc}): ${esc(p.name)}</option>`).join('');
  $('startupRows').innerHTML = cart.view.startup.map((r) => `
    <div class="srow"><span>ch${r.ch}</span><div class="ops"><select data-ch="${r.ch}">${opts}</select>
      <button class="btn" data-set="${r.ch}">これにする…</button><button class="btn" data-reset="${r.ch}">ふつうに戻す…</button></div>
      <span class="txt">いま: ${esc(r.text)}</span></div>`).join('');
  $('tidyRows').innerHTML = cart.view.tidy.map((r) => `
    <div class="srow"><span>ch${r.ch}</span><div class="ops"><button class="btn" data-tidy="${r.ch}">整える…</button>
      <button class="btn" data-base="${r.ch}">土台を今だけ送る</button></div>
      <span class="txt ${r.kind}">${esc(r.text)}</span></div>`).join('');
  $('startupRows').querySelectorAll('[data-set]').forEach((b) => (b.onclick = () => {
    const pc = $('startupRows').querySelector(`select[data-ch="${b.dataset.set}"]`).value;
    if (!pc) { toast('音色の入った場所がありません'); return; }
    runPlan('startup', +b.dataset.set, +pc);
  }));
  $('startupRows').querySelectorAll('[data-reset]').forEach((b) => (b.onclick = () => runPlan('startup_reset', +b.dataset.reset)));
  $('tidyRows').querySelectorAll('[data-tidy]').forEach((b) => (b.onclick = () => runPlan('tidy', +b.dataset.tidy)));
  $('tidyRows').querySelectorAll('[data-base]').forEach((b) => (b.onclick = async () =>
    toast((await api.send_base(+b.dataset.base)) ? '土台を送りました(保存はしていません)' : 'このチャンネルには共通の土台がありません')));
}

// ---------- 起動時の配線 ----------
window.addEventListener('pywebviewready', async () => {
  await refreshLib();
  await refreshSets();
  $('libKind').onclick = (e) => { if (e.target.dataset.k) showKind(e.target.dataset.k); };
  $('libSearch').oninput = (e) => { lib.filter = e.target.value; renderLib(); };
  $('libLoad').onclick = loadSelected;
  $('libNew').onclick = async () => {
    if (lib.kind === 'set') {
      const f = await setForm('いまの 5ch と割り当て表を演奏セットとして保存');
      if (!f) return;
      const r = await api.set_save_new(f.name, f.notes);
      if (r.error) { toast(r.error); return; }
      await refreshSets(r.id);
      toast('演奏セットを保存しました');
      return;
    }
    const f = await patchForm(`ch${state.ch} の今の音を新しく保存`);
    if (!f) return;
    const r = await api.lib_save_new(state.ch, f.name, f.category, f.notes);
    if (r.error) { toast(r.error); return; }
    await refreshLib(r.id);
    applyState(r.state);
    toast('ライブラリに保存しました');
  };
  $('libOver').onclick = async () => {
    if (lib.kind === 'set') {
      const d = lib.sets.find((x) => x.id === lib.ssel);
      if (!d) { toast('上書きする演奏セットを一覧から選んでください'); return; }
      if (!(await ask('上書き保存', `「${d.name}」を、いまの 5ch の音色と割り当て表で上書きします。`, '上書きする'))) return;
      const r = await api.set_overwrite(d.id);
      if (r.error) { toast(r.error); return; }
      await refreshSets(d.id);
      return;
    }
    const p = lib.list.find((x) => x.id === lib.sel);
    if (!p) { toast('上書きする音色を一覧から選んでください'); return; }
    let msg = `「${p.name}」を、ch${state.ch} の今の音で上書きします。`;
    if (p.channel !== state.ch) msg += `\n\n注意: この音色は ch${p.channel} 用ですが、ch${state.ch} として保存されます。`;
    if (!(await ask('上書き保存', msg, '上書きする'))) return;
    const r = await api.lib_overwrite(p.id, state.ch);
    if (r.error) { toast(r.error); return; }
    await refreshLib(p.id);
    applyState(r.state);
  };
  $('libMeta').onclick = async () => {
    if (lib.kind === 'set') {
      const d = lib.ssel && (await api.set_info(lib.ssel));
      if (!d) { toast('一覧から演奏セットを選んでください'); return; }
      const f = await setForm('名前・メモ', d);
      if (f) { await api.set_meta(d.id, f.name, f.notes); await refreshSets(d.id); }
      return;
    }
    const p = lib.sel && (await api.lib_info(lib.sel));
    if (!p) { toast('一覧から音色を選んでください'); return; }
    const f = await patchForm('名前・メモ', p);
    if (f) { await api.lib_meta(p.id, f.name, f.category, f.notes); await refreshLib(p.id); }
  };
  $('libDel').onclick = async () => {
    if (lib.kind === 'set') {
      const d = lib.sets.find((x) => x.id === lib.ssel);
      if (!d) return;
      if (await ask('削除', `演奏セット「${d.name}」をライブラリから削除します。\n(パソコンの一覧から消すだけで、カートリッジには影響しません)`, '削除する', true)) {
        await api.set_delete(d.id);
        await refreshSets(null);
      }
      return;
    }
    const p = lib.list.find((x) => x.id === lib.sel);
    if (!p) return;
    if (await ask('削除', `「${p.name}」をライブラリから削除します。\n(PC上の一覧から消すだけで、カートリッジには影響しません)`, '削除する', true)) {
      await api.lib_delete(p.id);
      await refreshLib(null);
    }
  };
  $('libCart').onclick = openCart;
  $('btnCart').onclick = openCart;
  $('cartClose').onclick = () => $('cartPage').classList.remove('open');
  $('btnTry').onclick = async () => { if (!(await api.cart_try(cart.sel, +$('tryCh').value))) toast('書き込み中です'); };
  $('btnPut').onclick = () => runPlan('save', cart.sel, $('putSel').value);
  $('btnClear').onclick = () => runPlan('clear', cart.sel);
});
