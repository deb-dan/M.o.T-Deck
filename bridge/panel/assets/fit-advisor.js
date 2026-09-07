/* ══════ THE RAM FIT ADVISOR — panel side (v1.5.30) ══════════════════════════
   The bridge owns every number and every sentence here (bridge/core/fit.py +
   bridge/core/memory.py). That is deliberate and it is the whole reason the engine
   was built first: the chip on a row, the line in the detail pane, the consent panel
   and what an API client is told are ONE answer rendered four ways. LM Studio's
   documented defect is a browser badge and a loader that price the same model
   differently; there is no arithmetic in this file that could drift from the bridge.

   The one thing the panel decides is WHEN to speak: a chip always, a line on the
   selected model, and a panel only when a load would not fit — and never twice for
   the same decision (see fitAcked, the cry-wolf rule). */
let memLedger = null;        // last /api/memory/fits payload (ledger + every verdict)
let memFits = {};            // model id → verdict
let memOpen = false;         // is the ledger expanded?
let memExternal = null;      // top OUTSIDE consumers, only fetched when expanded
let fitConsent = null;       // {id, name, advisory} while a load waits for consent
let auxWarn = '';            // the aux slot's pending fit warning, if any
const fitAcked = {};         // model id → true once the user has proceeded anyway.
                             // CRY-WOLF RULE: a risk the user has already accepted is
                             // not re-litigated on the next load of the same model.
const MEM_GB = 1073741824;

function memGB(b){ return (Number(b || 0) / MEM_GB).toFixed(1); }
function shortName(s){ s = String(s || ''); return s.length > 26 ? s.slice(0, 25) + '…' : s; }

let memAudioFits = {};       // audio model id → verdict (the Audio tab's chips)
let fitMathOpen = false;     // detail pane: is the arithmetic disclosed?

function advisorPrefs(){
  return (memLedger && memLedger.advisor) || {mode:'advise', custom_headroom_gb:4,
                                              remember_overrides:true};
}

function advisorModeLabel(mode){
  return ({quiet:'Quiet', advise:'Advise', early:'Advise early', custom:'Custom headroom'})[mode]
      || 'Advise';
}

function advisorModePreview(mode){
  if (!memLedger) return;
  memLedger.advisor = Object.assign({}, advisorPrefs(), {mode:mode});
  renderMemStrip();
}

async function advisorSave(){
  const modeEl = document.getElementById('mem-advisor-mode');
  const headEl = document.getElementById('mem-advisor-headroom');
  const rememberEl = document.getElementById('mem-advisor-remember');
  if (!modeEl) return;
  const payload = {mode:modeEl.value,
    custom_headroom_gb:Number((headEl && headEl.value) || 0),
    remember_overrides:!!(rememberEl && rememberEl.checked)};
  try {
    const response = await fetch('/api/memory/advisor', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({advisor:payload})});
    const result = await response.json();
    if (!result.ok){ chatNotice(result.error || 'advisor setting was not saved'); return; }
    if (!payload.remember_overrides){
      for (const key of Object.keys(fitAcked)) delete fitAcked[key];
    }
    chatNotice('memory advice: ' + advisorModeLabel(payload.mode).toLowerCase());
    await refreshMemory();
  } catch (e) { chatNotice('memory advice setting could not reach the bridge'); }
}

async function refreshMemory(){
  let r = null;
  try { r = await (await fetch('/api/memory/fits')).json(); } catch (e) { return; }
  if (!r || !r.ok) return;
  memLedger = r; memFits = r.fits || {}; memAudioFits = r.audio_fits || {};
  renderMemStrip();
  paintFitChips();
  paintAudioFitChips();
  try { renderDetail(); } catch (e) {}
}

/* ══ THE VERDICT TOOLTIP — ONE PAYLOAD, THREE INPUT METHODS ═══════════════════
   Debi's ruling (2026-08-29): the row keeps the CHIP; the sentence, the arithmetic
   and the hedge move to a hover. The implementation detail that matters is that
   hover alone would ship the feature to half its users and none of its taps —
   WKWebView does not reliably render `title`, and a trackpad hover is not a tap. So
   every tipped chip answers to mouseenter, to click, and to keyboard focus, and the
   `title` attribute is set underneath as the fallback that costs nothing.

   ONE payload builds both, so a tooltip can never contradict the chip it belongs to
   (the LIE class: a green chip whose hover says "over by 4 GB"). Both are read off
   the same verdict object, formatted by the same function. */
let _tipEl = null, _tipFor = null;
function tipNode(){
  if (_tipEl) return _tipEl;
  _tipEl = document.createElement('div');
  _tipEl.className = 'fit-tip float-surface';
  _tipEl.hidden = true;
  _tipEl.setAttribute('role', 'tooltip');
  document.body.appendChild(_tipEl);
  return _tipEl;
}
function tipHide(){ const t = tipNode(); t.hidden = true; _tipFor = null; }
function tipShow(el, html){
  const t = tipNode();
  t.innerHTML = html;
  t.hidden = false;
  _tipFor = el;
  // Measured AFTER it is in the DOM and visible: an offsetWidth read on a hidden node
  // is 0, which parked every tooltip at the left edge in the first walk.
  const r = el.getBoundingClientRect();
  const w = t.offsetWidth, h = t.offsetHeight;
  let left = Math.min(r.left, window.innerWidth - w - 10);
  let top = r.bottom + 8;
  if (top + h > window.innerHeight - 10) top = Math.max(10, r.top - h - 8);
  t.style.left = Math.max(10, left) + 'px';
  t.style.top = top + 'px';
}
function tipBind(el, html, plain){
  if (!el) return;
  el.classList.add('tipped');
  el.setAttribute('tabindex', '0');
  el.title = plain || '';                 // last-resort fallback, never the only path
  el._tipHtml = html;
  // THE LEDGER PUSHES EVERY COUPLE OF SECONDS AND THE CHIP IS REPAINTED IN PLACE. If
  // the tip for this chip is open while that happens, it must move with it — a tooltip
  // showing the previous sample beside a chip showing the current one is the exact
  // chip-contradicts-its-own-hover lie this payload is shared to prevent.
  if (_tipFor === el) tipShow(el, html);
  if (el._tipWired) return;
  el._tipWired = true;
  el.addEventListener('mouseenter', () => tipShow(el, el._tipHtml));
  el.addEventListener('mouseleave', () => { if (_tipFor === el) tipHide(); });
  el.addEventListener('focus', () => tipShow(el, el._tipHtml));
  el.addEventListener('blur', () => { if (_tipFor === el) tipHide(); });
  // THE TAP PATH. stopPropagation because these chips sit inside clickable rows, and
  // a tap that both opened the tip and navigated away would show it for one frame.
  el.addEventListener('click', (e) => {
    e.stopPropagation();
    if (_tipFor === el) tipHide(); else tipShow(el, el._tipHtml);
  });
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); e.stopPropagation();
      if (_tipFor === el) tipHide(); else tipShow(el, el._tipHtml); }
  });
}
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') tipHide(); }, true);
window.addEventListener('scroll', () => tipHide(), true);
window.addEventListener('resize', () => tipHide(), true);

/* PURE: the tooltip body for one verdict. The chip is NOT repeated inside it — the
   chip is the thing being hovered and is still on screen. */
function fitTipHtml(v){
  if (!v || !v.copy) return '';
  const c = v.copy;
  let h = '<span class="t-line">' + esc(c.line || '') + '</span>';
  if (c.math) h += '<span class="t-math">' + esc(c.math) + '</span>';
  if (c.remedy) h += '<span class="t-line">' + esc(c.remedy) + '</span>';
  if (c.hedge) h += '<span class="t-hedge">' + esc(c.hedge) + '</span>';
  if (c.caveat) h += '<span class="t-hedge">' + esc(c.caveat) + '</span>';
  return h;
}
function fitTipPlain(v){
  if (!v || !v.copy) return '';
  const c = v.copy;
  return [c.line, c.math, c.remedy, c.hedge].filter(Boolean).join('  ');
}

function memDotClass(p){ return p === 'critical' ? 'crit' : (p === 'warn' ? 'warn' : ''); }

/* Pressure, not fill — Activity Monitor's semantics, in our words. A machine whose
   RAM is entirely spoken for is HEALTHY if the kernel says pressure is normal; a
   fill bar alone would cry wolf every day. The bar under the headline is context,
   never the verdict. */
function memHeadline(sys){
  const p = (sys && sys.pressure) || 'normal';
  if (p === 'critical') return 'Memory pressure: critical — the machine is swapping now.';
  if (p === 'warn') return 'Memory pressure: elevated — macOS is compressing to keep up.';
  return 'Memory pressure: normal.';
}

function renderMemStrip(){
  const el = document.getElementById('mem-strip');
  if (!el) return;
  if (!memLedger || !memLedger.system){ el.hidden = true; return; }
  el.hidden = false;
  const sys = memLedger.system, bud = memLedger.budget || {};
  // Both budgets, because both are true and one alone misleads: the resident model's
  // weights are GPU-wired, so "usable now" and "usable after a switch" differ by the
  // whole model. Measured here: 5.0 GB vs 14.9 GB.
  const after = memLedger.budget_after_eject;
  const total = Number(sys.total_bytes || 0);
  const ours = Number(memLedger.ours_bytes || 0);
  const other = Number(memLedger.other_bytes || 0);
  const pct = (b) => total ? Math.max(0, Math.min(100, 100 * b / total)) : 0;
  // ══ STATUS + DELTA, THE GRAMMAR DEBI CHOSE (2026-08-29) ═══════════════════════
  // WAS: "…~15.5 GB usable for a model right now, ~30.3 GB once <60-char-model-id> is
  // ejected — of 64.0 GB." One sentence carrying three numbers, a model id and a
  // subordinate clause, in a strip that is read at a glance.
  // NOW: pressure first (unchanged — it is the only thing here that is a warning),
  // then two figures in the shape she named: what is free, and what a switch adds.
  // The INTENT-BASED pair — "Run alongside" vs "Replace active (eject X)" — is one
  // level down, on the strip's own hover and in Details, because it answers a
  // question ("which of these two am I doing?") that only some readings are asking.
  const freeNow = Number(bud.budget_bytes || 0);
  const afterB = after ? Number(after.budget_bytes || 0) : 0;
  const delta = afterB ? Math.max(0, afterB - freeNow) : 0;
  const headline = `Free now: ~${memGB(freeNow)} GB`
      + (delta ? ` · +${memGB(delta)} GB on eject` : '');
  const intent = `Run alongside: ~${memGB(freeNow)} GB`
      + (afterB ? ` · Replace active (eject ${shortName(memLedger.live_model)}): ~${memGB(afterB)} GB`
                : '')
      + `. Of ${memGB(total)} GB installed; we hold ${memGB(ours)} GB, everything else `
      + `holds ${memGB(other)} GB.`;
  const head = `<div class="mem-head">
      <span class="mem-dot ${memDotClass(sys.pressure)}"></span>
      <span class="mem-title">Memory</span>
      <span class="mem-sub" id="mem-sub">${esc(memHeadline(sys))} ${esc(headline)}</span>
      <button class="mem-more" onclick="toggleMemLedger()">${memOpen ? 'Less' : 'Details'}</button>
    </div>
    <div class="mem-bar">
      <div class="mem-seg ours" style="width:${pct(ours).toFixed(2)}%"></div>
      <div class="mem-seg other" style="width:${pct(other).toFixed(2)}%"></div>
    </div>`;
  let body = '';
  if (memOpen){
    // The intent pair, spelled out where there is room for it.
    body += `<div class="mem-note">${esc(intent)}</div>`;
    const rows = (memLedger.components || []).slice()
      .sort((a, b) => (b.footprint_bytes || 0) - (a.footprint_bytes || 0));
    body += '<div class="mem-rows">';
    for (const c of rows){
      const nm = (c.name === 'runner' && memLedger.live_model) ? memLedger.live_model
                                                              : (c.label || c.name);
      const peak = (c.peak_bytes && c.peak_bytes > c.footprint_bytes * 1.2)
        ? `<span class="pk">peak ${memGB(c.peak_bytes)}</span>` : '';
      body += `<div class="mem-row"><span class="nm">${esc(nm)}</span>${peak}
               <span class="gb">${memGB(c.footprint_bytes)} GB</span></div>`;
    }
    body += `<div class="mem-row"><span class="nm">Everything else on this Mac</span>
             <span class="gb">${memGB(other)} GB</span></div>`;
    if (memExternal && memExternal.length){
      for (const e of memExternal){
        body += `<div class="mem-row"><span>· ${esc(e.name)}</span>
                 <span class="gb">${memGB(e.footprint_bytes)} GB</span></div>`;
      }
    }
    body += '</div>';
    const alloc = memLedger.runner_allocation;
    if (alloc && Number(alloc.allocation_bytes || 0)){
      const pred = alloc.prediction || {};
      body += `<div class="mem-note"><span class="nm">Runner allocation:</span> `
        + `${memGB(alloc.allocation_bytes)} GB reported by llama.cpp after loading`
        + (pred.known ? ` · predicted ${memGB(pred.total_bytes)} GB`
            + (Number.isFinite(Number(pred.delta_pct)) ? ` · delta ${Number(pred.delta_pct) >= 0 ? '+' : ''}${Number(pred.delta_pct).toFixed(1)}%` : '') : '')
        + `. This is allocated model/context/working capacity, not the process footprint above.</div>`;
    }
    const swap = sys.swap_used_bytes ? ` Swap in use: ${memGB(sys.swap_used_bytes)} GB` +
      (sys.compression_ratio ? `, compression ${sys.compression_ratio}:1` : '') +
      ' — normal on macOS while pressure is normal.' : '';
    body += `<div class="mem-note">${esc(memLedger.metric_note || '')}${esc(swap)}
      GPU-wireable ceiling: ${memGB(sys.metal_ceiling_bytes)} GB of ${memGB(total)} GB.
      We name what other apps hold; we never touch them.</div>`;
    const policy = advisorPrefs();
    const custom = policy.mode === 'custom';
    body += `<div class="mem-policy">
      <label for="mem-advisor-mode">When to interrupt a load</label>
      <select id="mem-advisor-mode" onchange="advisorModePreview(this.value)">
        <option value="quiet"${policy.mode === 'quiet' ? ' selected' : ''}>Quiet · chips only</option>
        <option value="advise"${policy.mode === 'advise' ? ' selected' : ''}>Advise · when over</option>
        <option value="early"${policy.mode === 'early' ? ' selected' : ''}>Advise early · tight or over</option>
        <option value="custom"${custom ? ' selected' : ''}>Custom headroom</option>
      </select>
      ${custom ? `<label for="mem-advisor-headroom">Reserve</label>
        <input id="mem-advisor-headroom" type="number" min="0" max="256" step="0.5"
          value="${Number(policy.custom_headroom_gb || 0)}" aria-label="Custom memory headroom in GB">
        <span>GB</span>` : `<input id="mem-advisor-headroom" type="hidden"
          value="${Number(policy.custom_headroom_gb || 0)}">`}
      <label><input id="mem-advisor-remember" type="checkbox"${policy.remember_overrides ? ' checked' : ''}>
        don't warn again for models I've overridden</label>
      <button class="save" onclick="advisorSave()">Save</button>
    </div>`;
  }
  el.innerHTML = head + body;
  // The strip's own hover carries the intent pair too, so the answer is one gesture
  // away without opening the ledger. Same payload as the Details line above.
  const sub = document.getElementById('mem-sub');
  if (sub) tipBind(sub, '<span class="t-line">' + esc(intent) + '</span>'
    + '<span class="t-hedge">Pressure is the warning; a full machine at normal '
    + 'pressure is healthy.</span>', intent);
}

async function toggleMemLedger(){
  memOpen = !memOpen;
  renderMemStrip();
  if (memOpen && memExternal === null){
    try {
      const r = await (await fetch('/api/memory?external=1')).json();
      memExternal = (r && r.external) || [];
    } catch (e) { memExternal = []; }
    renderMemStrip();
  }
}

function fitChipClass(v){
  if (v === 'fits') return 'fit-ok';
  if (v === 'tight') return 'fit-slow';
  if (v === 'over') return 'fit-no';
  if (v === 'live') return 'fit-live';   // measured, not predicted — see live_verdict()
  return 'fit-unk';
}

/* Chips are patched IN PLACE rather than re-rendered. The ledger pushes every couple
   of seconds while this view is open, and rebuilding the list on each push would
   fight the user's scroll position and drop their selection — the row is the same
   row; only the verdict moved. */
function paintFitChips(){
  const nodes = document.querySelectorAll('#models-listcol .mrow');
  for (const row of nodes){
    const chip = row.querySelector('.mfit');
    if (!chip) continue;
    const v = memFits[row.dataset.mid];
    if (!v || !v.copy || !v.copy.chip){ chip.hidden = true; continue; }
    chip.hidden = false;
    chip.className = 'fitpill mfit ' + fitChipClass(v.verdict);
    // THE ROW IS THE CHIP AND NOTHING ELSE (Debi, 2026-08-29). The sentence, the
    // arithmetic and the hedge are the tooltip's, and both come off THIS object.
    chip.textContent = v.copy.chip;
    tipBind(chip, fitTipHtml(v), fitTipPlain(v));
  }
}

/* The Audio tab's chips — the same painter, the same grammar, a different list.
   Before this slice the voice rows carried no verdict at all, which read as "these
   cost nothing"; a resident TTS worker is measured in gigabytes like everything else. */
function paintAudioFitChips(){
  const nodes = document.querySelectorAll('#audio-listcol .mrow');
  for (const row of nodes){
    const chip = row.querySelector('.afit');
    if (!chip) continue;
    const v = memAudioFits[row.dataset.aid];
    if (!v || !v.copy || !v.copy.chip){ chip.hidden = true; continue; }
    chip.hidden = false;
    chip.className = 'fitpill afit ' + fitChipClass(v.verdict);
    chip.textContent = v.copy.chip;
    tipBind(chip, fitTipHtml(v), fitTipPlain(v));
  }
}

/* THE DETAIL PANE, RESTRUCTURED (Debi, 2026-08-29). It used to print four lines at
   once — verdict, need-vs-free, the weights+context+working arithmetic and the hedge —
   which is the "text wall" she named. It is now chip + ONE line, with the arithmetic
   and the hedge behind a disclosure. Nothing was deleted and nothing moved to a place
   it cannot be found: the same three facts are one click down, and the tooltip on the
   row's own chip carries them too. */
function fitDetailHtml(mid){
  const v = memFits[mid];
  if (!v || !v.copy) return '';
  const c = v.copy;
  const deep = (c.math || c.hedge);
  const more = deep
    ? (fitMathOpen
        ? `<button class="fit-more" onclick="fitToggleMath()">Hide the arithmetic</button>`
          + (c.math ? `<div class="fit-math">${esc(c.math)}</div>` : '')
          + (c.hedge ? `<div class="fit-hedge">${esc(c.hedge)}</div>` : '')
          + (c.caveat ? `<div class="fit-hedge">${esc(c.caveat)}</div>` : '')
        : `<button class="fit-more" onclick="fitToggleMath()">Show the arithmetic</button>`)
    : '';
  const measured = v.measurement;
  const measuredLine = measured && Number(measured.allocation_bytes || 0)
    ? `<div class="fit-hedge">Last runner allocation: ${memGB(measured.allocation_bytes)} GB`
      + ` at ${Number(measured.ctx || 0) >= 1024 ? Math.round(Number(measured.ctx) / 1024) + 'k' : Number(measured.ctx || 0)} context`
      + ` · model ${memGB(measured.model_bytes)} GB + context ${memGB(measured.context_bytes)} GB`
      + ` + working ${memGB(measured.working_bytes)} GB. Engine-reported allocation, not footprint.</div>`
    : '';
  return `<div class="fit-line"><span class="fitpill ${fitChipClass(v.verdict)}">${esc(c.chip)}</span>
          <span class="num"> ${esc(c.line || '')}</span>${more}${measuredLine}</div>`;
}
function fitToggleMath(){ fitMathOpen = !fitMathOpen; renderDetail(); }

function fitCancel(){ fitConsent = null; renderDetail(); }

/* THE CONSENT PANEL — verdict → reason → remedies → proceed, inline, never a modal.
   "Load anyway" is a plain visible button with the consequence in its own sentence:
   the override is ours by ruling, and hiding it behind a modifier key (the field's
   clever move) is an override only the people who read release notes can find. */
function fitConsentHtml(){
  if (!fitConsent) return '';
  const a = fitConsent.advisory || {};
  const c = a.copy || {};
  const hard = !!(a.refuse);
  let rem = '';
  for (const r of (a.remedies || [])){
    if (r.kind === 'ctx'){
      rem += `<button onclick="fitApplyCtx(${Number(r.value)})">${esc(r.text)} · use ${esc(r.label)}</button>`;
    } else if (r.kind === 'kv_quant'){
      rem += `<button onclick="fitTryKv('${escAttr(String(r.value))}')">${esc(r.text)} · use it</button>`;
    } else {
      rem += `<button onclick="fitCheckAgain()">${esc(r.text)} · re-check after</button>`;
    }
  }
  const act = hard
    ? `<button onclick="fitCancel()">Close</button>`
    : `<button onclick="fitCancel()">Not now</button>
       <button class="go" onclick="fitProceed()">Load anyway</button>`;
  const why = hard
    ? `${esc(a.refuse.reason)}<br>${esc(a.refuse.remedy)}`
    : `${esc(c.line || '')}<br>${esc(c.math || '')}`;
  return `<div class="fit-consent${hard ? ' hard' : ''}">
      <div class="fc-head">${esc(hard ? 'This context is past what this Mac can wire' : (c.chip || 'Probably will not fit'))}</div>
      <div class="fc-why">${why}</div>
      ${rem ? `<div class="fc-rem">${rem}</div>` : ''}
      <div class="fc-act">${act}</div>
      <div class="fc-hedge">${esc(c.hedge || '')} ${esc(c.caveat || '')}</div>
    </div>`;
}

async function fitRefetch(extra){
  if (!fitConsent) return;
  let url = '/api/memory/fit?id=' + encodeURIComponent(fitConsent.id) + (extra || '');
  try {
    const r = await (await fetch(url)).json();
    if (r && r.ok){ fitConsent.advisory = r; renderDetail(); }
  } catch (e) {}
}

function fitCheckAgain(){ fitRefetch(''); }

/* ⚠️ A REMEDY MUST CHANGE WHAT LOADS, NOT ONLY WHAT THE PANEL SAYS. Caught in the
   adversarial pass: the first version of the KV-cache remedy re-PRICED the model at
   q8_0 and flipped the chip to "Fits · ~18.3 GB", but Load anyway still loaded the
   SAVED settings — f16 KV, 20.2 GB, the configuration the panel had just declared
   fine. A green verdict over a red load is the worst thing this feature can ship, so
   both remedies write through the endpoint that owns load settings. The change is
   visible in the Load group afterwards, and undoable there. */
async function fitApplyLoad(patch){
  if (!fitConsent) return;
  try {
    await fetch('/api/models/load-settings', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({id: fitConsent.id, load: patch})});
  } catch (e) {}
  await initModels();
  await refreshMemory();
  fitRefetch('');
}
function fitApplyCtx(ctx){ return fitApplyLoad({ctx: ctx}); }
function fitTryKv(v){ return fitApplyLoad({kv_quant: v}); }

function fitProceed(){
  if (!fitConsent) return;
  const id = fitConsent.id, name = fitConsent.name;
  if (advisorPrefs().remember_overrides) fitAcked[id] = true;
  fitConsent = null;
  switchModel(id, name, true);
}
