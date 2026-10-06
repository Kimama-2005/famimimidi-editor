// 詳細な管理(C4b): 1つずつ試す、まとめて割り当て、くわしく設定して入れる、内部の対応表。上級者向け。
'use strict';

const ex = { tables: null, chk: 89, results: {}, bulkSel: new Set(), plan: {}, adv: [] };

async function openExpert() {
  ex.tables = await api.cart_tables();
  renderCheck();
  renderBulk();
  await renderAdvSelectors();
  renderTables();
  openPage('expertPage');
}
async function refreshExpert() {
  if (!$('expertPage').classList.contains('open')) return;
  ex.tables = await api.cart_tables();
  renderCheck();
  renderBulk();
  renderTables();
}
const pcLabel = (pc) => (ex.tables.pcs.find((p) => p.pc === pc) || {}).label || '';
const macroText = (m) => {
  const x = ex.tables.macros[m - 1];
  return `${m}: ${x.label}${x.use ? ` [${x.use}]` : ''}${ex.tables.free.includes(m) ? ' ← 空き' : ''}`;
};

// ---------- 1つずつ試す ----------
function renderCheck() {
  const r = ex.results[ex.chk];
  $('chkPc').textContent = `PC${ex.chk}(送信値${ex.chk - 1}・場所${ex.chk - 88})` + (r === undefined ? '' : r ? ' → 鳴った' : ' → 無音');
  $('chkLabel').textContent = `対応表: ${pcLabel(ex.chk)}`;
  const ng = Object.entries(ex.results).filter(([, ok]) => !ok).map(([pc]) => pc);
  $('chkSummary').textContent = `試した数 ${Object.keys(ex.results).length}/40 ・ 無音だった PC: ${ng.join(', ') || 'なし'}`;
}
async function chkMark(ok) {
  ex.results[ex.chk] = ok;
  await api.check_mark(ex.chk, ok);
  if (ex.chk < 128) { ex.chk++; renderCheck(); await api.check_play(ex.chk); } else renderCheck();
}

// ---------- まとめて割り当て ----------
function renderBulk() {
  const grid = $('bulkGrid');
  grid.innerHTML = '';
  ex.tables.pcs.forEach((p) => {
    const d = document.createElement('div');
    d.className = (ex.bulkSel.has(p.pc) ? 'sel ' : '') + (ex.results[p.pc] === false ? 'ng' : '');
    d.textContent = `${p.pc}: ${p.label}`;
    d.title = `PC${p.pc}(場所${p.pc - 88}): マクロ${p.m ?? '?'} ${p.label}`;
    d.onclick = () => { ex.bulkSel.has(p.pc) ? ex.bulkSel.delete(p.pc) : ex.bulkSel.add(p.pc); renderBulk(); };
    grid.appendChild(d);
  });
  const sel = $('bulkMacro');
  const cur = sel.value || '19';
  sel.innerHTML = '';
  for (let m = 1; m <= 40; m++) sel.add(new Option(macroText(m), m));
  sel.value = cur;
  const lines = Object.entries(ex.plan).map(([pc, m]) => `PC${pc} ← マクロ${m}`);
  $('bulkPlan').textContent = lines.length ? `予定 ${lines.length} 件: ` + lines.join('、') : '予定はまだありません';
}

// ---------- くわしく設定して入れる ----------
async function renderAdvSelectors() {
  const ps = $('advPatch');
  const cur = ps.value || lib.sel || '';
  ps.innerHTML = '';
  lib.list.forEach((p) => ps.add(new Option(`${p.name}(ch${p.channel}用)`, p.id)));
  if (cur) ps.value = cur;
  const pcs = $('advPc');
  const curPc = pcs.value || String(cart.sel || 89);
  pcs.innerHTML = '<option value="">(割り当てない)</option>' +
    ex.tables.pcs.map((p) => `<option value="${p.pc}">PC${p.pc}(場所${p.pc - 88}): ${esc(p.label)}</option>`).join('');
  pcs.value = curPc;
  await loadCandidates();
}
async function loadCandidates() {
  const pid = $('advPatch').value, pc = $('advPc').value || 89;
  if (!pid) return;
  const r = await api.cart_candidates(pid, +pc);
  ex.adv = r.rows;
  const ms = $('advMacro');
  ms.innerHTML = '';
  for (let m = 1; m <= 40; m++) ms.add(new Option(macroText(m) + (m === r.auto_macro ? '(自動で選ぶ番号)' : ''), m));
  if (r.auto_macro) ms.value = r.auto_macro;
  renderAdvRows();
}
function renderAdvRows() {
  const t = $('advRows');
  t.innerHTML = '<tr><th>順</th><th>設定</th><th>値</th><th></th></tr>';
  ex.adv.forEach(([cc, v, name, label], i) => {
    const tr = document.createElement('tr');
    tr.className = i >= 10 ? 'out' : '';
    tr.innerHTML = `<td>${i + 1}</td><td>${esc(name)}</td><td>${esc(label)}</td><td>
      <button class="btn mini" data-mv="-1">↑</button><button class="btn mini" data-mv="1">↓</button><button class="btn mini" data-rm>✕</button>
      ${i >= 10 ? '<span class="note">入らない</span>' : ''}</td>`;
    tr.querySelectorAll('[data-mv]').forEach((b) => (b.onclick = () => {
      const j = i + +b.dataset.mv;
      if (j < 0 || j >= ex.adv.length) return;
      [ex.adv[i], ex.adv[j]] = [ex.adv[j], ex.adv[i]];
      renderAdvRows();
    }));
    tr.querySelector('[data-rm]').onclick = () => { ex.adv.splice(i, 1); renderAdvRows(); };
    t.appendChild(tr);
  });
}

// ---------- 内部の対応表 ----------
function renderTables() {
  const ms = $('asgMacro'), curM = ms.value;
  ms.innerHTML = '';
  for (let m = 1; m <= 40; m++) ms.add(new Option(macroText(m), m));
  if (curM) ms.value = curM;
  const ps = $('asgPc'), curP = ps.value;
  ps.innerHTML = '<option value="">(しない)</option>' + ex.tables.pcs.map((p) => `<option value="${p.pc}">PC${p.pc}(場所${p.pc - 88}): ${esc(p.label)}</option>`).join('');
  ps.value = curP || '';
  $('tblMacros').innerHTML = '<tr><th>番号</th><th>内容</th><th>項目数</th><th>使用先</th><th>書き込み</th></tr>' +
    ex.tables.macros.map((x) => `<tr class="clickable" data-m="${x.m}"><td>${x.m}${x.reserved ? '*' : ''}</td><td>${esc(x.label)}${x.certain ? '' : '(推定)'}</td>
      <td>${x.count ?? '?'}</td><td>${esc(x.use)}</td><td>${esc(x.written)}</td></tr>`).join('');
  $('tblMacros').querySelectorAll('[data-m]').forEach((tr) => (tr.onclick = () => {
    const x = ex.tables.macros[tr.dataset.m - 1];
    info(`マクロ${x.m} の中身`, x.count === null ? '中身: 不明' : x.cc.map(([n, v]) => `・${n} = ${v}`).join('\n') || '(空)');
  }));
  $('tblPcs').innerHTML = '<tr><th>PC(送信値)</th><th>マクロ</th><th>内容</th></tr>' +
    ex.tables.pcs.map((p) => `<tr><td>PC${p.pc}(${p.pc - 1})</td><td>${p.m ?? '?'}</td><td>${esc(p.label)}</td></tr>`).join('');
  $('tblStartup').innerHTML = ex.tables.startup.map((r) => `<div>ch${r.ch}: ${esc(r.text)}</div>`).join('');
}

// ---------- 起動時の配線 ----------
window.addEventListener('pywebviewready', () => {
  $('btnExpert').onclick = openExpert;
  $('exTabs').onclick = (e) => {
    const t = e.target.dataset.t;
    if (!t) return;
    $('exTabs').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.t === t));
    document.querySelectorAll('.extab').forEach((d) => (d.style.display = d.id === `ex-${t}` ? '' : 'none'));
  };
  $('chkPrev').onclick = () => { ex.chk = Math.max(89, ex.chk - 1); renderCheck(); };
  $('chkNext').onclick = () => { ex.chk = Math.min(128, ex.chk + 1); renderCheck(); };
  $('chkPlay').onclick = async () => { if (!(await api.check_play(ex.chk))) toast('書き込み中です'); };
  $('chkOk').onclick = () => chkMark(true);
  $('chkNg').onclick = () => chkMark(false);
  $('chkToBulk').onclick = () => {
    Object.entries(ex.results).filter(([, ok]) => !ok).forEach(([pc]) => ex.bulkSel.add(+pc));
    renderBulk();
    $('exTabs').querySelector('[data-t=bulk]').click();
  };
  $('bulkAdd').onclick = () => {
    if (!ex.bulkSel.size) { toast('PC を選んでください'); return; }
    ex.bulkSel.forEach((pc) => (ex.plan[pc] = +$('bulkMacro').value));
    ex.bulkSel.clear();
    renderBulk();
  };
  $('bulkClearSel').onclick = () => { ex.bulkSel.clear(); renderBulk(); };
  $('bulkReset').onclick = () => { ex.plan = {}; renderBulk(); };
  $('bulkGo').onclick = async () => {
    if (!Object.keys(ex.plan).length) { toast('予定がありません'); return; }
    await runPlan('assign_many', null, ex.plan);
  };
  $('advPatch').onchange = loadCandidates;
  $('advPc').onchange = loadCandidates;
  $('advGo').onclick = () => {
    if (!ex.adv.length) { toast('記録する項目がありません'); return; }
    runPlan('advanced', null, { patch_id: $('advPatch').value, macro: +$('advMacro').value, pc: $('advPc').value || null,
                                startup_ch: $('advStartup').value || null, ccs: ex.adv.slice(0, 10).map(([c, v]) => [c, v]) });
  };
  $('asgGo').onclick = () => {
    const pc = $('asgPc').value, st = $('asgStartup').value;
    if (!pc && !st) { toast('PC か電源ONのどちらかを選んでください'); return; }
    runPlan('assign', +$('asgMacro').value, { pc: pc || null, startup_ch: st || null });
  };
  $('sendPc').oninput = () => { const pc = +$('sendPc').value; $('sendLabel').textContent = pc >= 89 && pc <= 128 ? pcLabel(pc) : ''; };
  $('sendGo').onclick = async () => {
    const pc = +$('sendPc').value;
    if (!(pc >= 1 && pc <= 128)) { toast('PC は 1〜128'); return; }
    await api.pc_send(+$('sendCh').value, pc);
  };
});
