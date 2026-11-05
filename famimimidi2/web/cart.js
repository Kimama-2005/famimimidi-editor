// ★ カートリッジ(SPEC_v2 7.4)と、書き込みの確認・実行(6.6.1)。計画と控えの更新は Python(cartridge/)。
'use strict';

const ct = { view: null, sel: null, token: null };
const KIND_COLOR = { pulse: 'var(--c1)', triangle: 'var(--c3)', noise: 'var(--c4)', dpcm_wave: 'var(--c5)' };

async function openCart() {
  ct.view = await api.cart_view();
  renderCart();
  openOv('ovCart');
}

function renderCart() {
  const v = ct.view;
  $('tiles').innerHTML = v.tiles.map((t) =>
    `<div class="tile ${t.empty ? '' : (t.unknown ? 'unknown' : 'filled')} ${t.place === ct.sel ? 'sel' : ''}" data-place="${t.place}">`
    + `<b>${t.place} / ${t.pc}</b>${t.kind ? `<i class="k" style="background:${KIND_COLOR[t.kind]}"></i>` : ''}${esc(t.empty ? '空き' : t.name)}</div>`).join('');
  const t = v.tiles.find((x) => x.place === ct.sel);
  $('placeHead').textContent = t ? `保存場所 ${t.place} ― 呼び出し番号 ${t.pc}` : '保存場所を選んでください';
  $('placeInfo').textContent = t ? `中身: ${t.empty ? '(空き)' : t.name}${t.unknown ? '(このアプリの記録には無い)' : ''}` : '';
  $('placeCh').innerHTML = v.slots.map((s) => `<option value="${s.ch}">${CHN[s.ch]}: ${esc(s.name || '(既定値)')}</option>`).join('');
  ['btnPlaceSave', 'btnPlaceCall', 'btnPlaceClear'].forEach((id) => { $(id).disabled = !t; });
  const placeOpts = v.tiles.filter((x) => !x.empty && !x.unknown).map((x) => `<option value="${x.place}">${x.place}: ${esc(x.name)}</option>`).join('');
  $('startupRows').innerHTML = v.startup.map((r) =>
    `<div class="srow"><b>ch${r.ch}</b><span class="txt">${esc(r.text)}</span>`
    + `<span class="ops"><select data-ch="${r.ch}"><option value="">変える…</option><option value="normal">ふつう(何も変えない)</option>${placeOpts}</select></span></div>`).join('');
  $('tidyRows').innerHTML = v.tidy.map((r) =>
    `<div class="srow"><b>ch${r.ch}</b><span class="txt ${r.kind}">${esc(r.text)}</span>`
    + `<span class="ops">${r.needed ? `<button class="btn mini" data-tidy="${r.ch}">整える…</button>` : ''}</span></div>`).join('');
}

/** 計画を作って確認画面を出す */
async function planAndConfirm(kind, args) {
  const r = await api.cart_plan(kind, args || {});
  if (r.error) { toast(r.error, 'danger'); return; }
  ct.token = r.token;
  $('cfTitle').textContent = `${r.title} ― 元に戻せません`;
  $('cfLines').innerHTML = r.lines.map((l) => `<div class="${l.startsWith('※') ? 'warn' : ''}">${esc(l)}</div>`).join('');
  $('cfTime').textContent = `かかる時間: 約 ${r.seconds} 秒。書き込みの間はファミコンの電源を切らないでください。`;
  $('cfDetail').textContent = r.detail;
  $('cfDetail').classList.remove('open');
  $('cfAgree').checked = false;
  $('cfYes').disabled = true;
  $('cfYes').textContent = r.ok_text;
  openOv('ovConfirm');
}

window.onWriteProgress = (i, n, text) => {
  $('wrBar').style.width = `${Math.round((i / n) * 100)}%`;
  $('wrText').textContent = text;
};
window.onWriteDone = async (ok, message) => {
  clearInterval(ct.overdueTimer);
  $('wrTitle').textContent = ok ? '書き込みが終わりました' : '書き込みに失敗しました';
  $('wrText').textContent = message;
  $('wrBar').style.width = ok ? '100%' : $('wrBar').style.width;
  $('wrClose').hidden = false;
  ct.view = await api.cart_view();
  renderCart();
};

window.addEventListener('pywebviewready', () => {
  $('btnCart').onclick = openCart;
  $('tiles').onclick = (e) => { const t = e.target.closest('[data-place]'); if (t) { ct.sel = +t.dataset.place; renderCart(); } };
  $('btnPlaceSave').onclick = () => planAndConfirm('save', { place: ct.sel, ch: +$('placeCh').value });
  $('btnPlaceClear').onclick = () => planAndConfirm('clear', { place: ct.sel });
  $('btnPlaceCall').onclick = async () => {
    await api.cart_call(ct.sel, +$('placeCh').value);
    toast(`保存場所 ${ct.sel} を ${CHN[+$('placeCh').value]} で呼び出しました。作業中の音色に戻すときは「送り直す」`);
  };
  $('startupRows').onchange = (e) => {
    const sel = e.target.closest('select[data-ch]');
    if (!sel || !sel.value) return;
    planAndConfirm('startup', { ch: +sel.dataset.ch, place: sel.value === 'normal' ? null : +sel.value });
    sel.value = '';
  };
  $('tidyRows').onclick = (e) => { const b = e.target.closest('[data-tidy]'); if (b) planAndConfirm('tidy', { ch: +b.dataset.tidy }); };
  $('btnPerfPlaces').onclick = () => {
    // 選んでいる保存場所(なければ1)から順に、空いている場所へ
    const free = ct.view.tiles.filter((t) => t.empty && t.place >= (ct.sel || 1)).map((t) => t.place);
    const places = {};
    ct.view.perf_chs.forEach((ch, i) => { if (free[i]) places[ch] = free[i]; });
    planAndConfirm('perf_places', { places });
  };
  $('btnPerfStartup').onclick = () => planAndConfirm('perf_startup', {});
  // 確認画面
  $('cfAgree').onchange = () => { $('cfYes').disabled = !$('cfAgree').checked; };
  $('cfShow').onclick = (e) => { e.preventDefault(); $('cfDetail').classList.toggle('open'); };
  $('cfNo').onclick = () => closeOv('ovConfirm');
  $('cfYes').onclick = async () => {
    if (!$('cfAgree').checked) return;
    closeOv('ovConfirm');
    const r = await api.cart_run(ct.token);
    if (r.error) { toast(r.error, 'danger'); return; }
    $('wrTitle').textContent = 'カートリッジに書き込み中';
    $('wrBar').style.width = '0%';
    $('wrText').textContent = '';
    $('wrClose').hidden = true;
    openOv('ovWrite');
    // 予定+20秒を過ぎても終わらなければ「応答がない」(閉じてよい)
    ct.overdueTimer = setInterval(async () => {
      if (await api.write_overdue()) {
        clearInterval(ct.overdueTimer);
        $('wrTitle').textContent = '応答がありません';
        $('wrText').textContent = '予定の時間を大きく過ぎても終わりません。閉じてかまいません(書いた所は控えで「不明」になります)。';
        $('wrClose').hidden = false;
      }
    }, 2000);
  };
  $('wrClose').onclick = () => closeOv('ovWrite');
  // 波形の登録(5 のタブから)
  $('waveSlot').innerHTML = Array.from({ length: 16 }, (_, i) => `<option value="${61 + i}">${61 + i}</option>`).join('');
  $('btnWaveNext').onclick = () => { closeOv('ovWave'); planAndConfirm('wave', { slot: +$('waveSlot').value, name: $('waveName').value }); };
});

/** tone.js の「カートリッジに登録…」から */
window.openWaveRegister = (name) => { $('waveName').value = name || ''; openOv('ovWave'); };
