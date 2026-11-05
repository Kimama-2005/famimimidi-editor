// ✓ 実機の確認モード(SPEC_v2 8.2)。手順と結果の記録は Python(checks.py・App.check_*)。
'use strict';

async function openCheck() {
  const r = await api.check_list();
  if (r.state.running) { showCheckStep(r.state); openOv('ovCheck'); return; }
  $('ckBody').innerHTML = (r.other_apps.length
    ? `<div class="dangertext">${esc(r.other_apps.join('・'))} が起動しています。鍵盤の演奏を直接流していると結果が混ざるので、閉じてから始めてください。</div>` : '')
    + '<div class="note">アプリが自分で音を送ります。鳴ったかどうかをボタンで答えてください。設定はアプリが変えて、終わったら(途中でやめても)元に戻します。結果は自動で記録されます。</div>'
    + r.checks.map((c) => `<div class="ckitem"><div><b>${esc(c.title)}</b><div class="note">${esc(c.description)}</div></div>`
      + `<button class="btn main" data-ck="${c.name}" ${c.steps ? '' : 'disabled'}>始める(${c.steps} 手順)</button></div>`).join('');
  $('ckRun').hidden = true;
  $('ckBody').hidden = false;
  $('ckTitle').textContent = '実機の確認';
  openOv('ovCheck');
}

function showCheckStep(st) {
  if (st.error) { toast(st.error, 'danger'); return; }
  if (st.done) { showCheckDone(st); return; }
  $('ckBody').hidden = true;
  $('ckRun').hidden = false;
  $('ckTitle').textContent = `実機の確認 ― ${st.title}`;
  $('ckSteps').innerHTML = Array.from({ length: st.n }, (_, i) => `<i class="${i < st.i ? 'done' : i === st.i ? 'now' : ''}"></i>`).join('');
  $('ckText').textContent = `${st.i + 1} / ${st.n} ― ${st.text}`;
  $('ckQ').textContent = st.question;
  $('ckButtons').hidden = false;
}

function showCheckDone(r) {
  $('ckRun').hidden = true;
  $('ckBody').hidden = false;
  $('ckTitle').textContent = `実機の確認 ― ${r.title || ''}`;
  $('ckBody').innerHTML = `<div class="q">${r.stopped ? '途中でやめました' : 'おわりました'}</div>`
    + `<div>答え ${r.answers ? r.answers.length : 0} 個${r.unexpected ? `(予想と違う答え ${r.unexpected} 個)` : ''}。設定は元に戻しました。</div>`
    + `<div class="note">結果は自動で記録しました: ${esc(r.file || '')}<br>Claude に「確認の結果を見て」と伝えてください。</div>`;
}

window.addEventListener('pywebviewready', () => {
  $('btnCheck').onclick = openCheck;
  $('ckBody').onclick = async (e) => { const b = e.target.closest('[data-ck]'); if (b) showCheckStep(await api.check_start(b.dataset.ck)); };
  $('ckYes').onclick = async () => showCheckStep(await api.check_answer('yes'));
  $('ckNo').onclick = async () => showCheckStep(await api.check_answer('no'));
  $('ckAgain').onclick = async () => showCheckStep(await api.check_again());
  $('ckStop').onclick = async () => showCheckStep(await api.check_stop());
  $('ckClose').onclick = async () => {
    const r = await api.check_list();
    if (r.state.running) showCheckDone(await api.check_stop());      // 閉じたらやめる(設定は元に戻す)
    closeOv('ovCheck');
  };
});
