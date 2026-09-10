/* v1.5.90 — ownership-safe uninstall and conversation-clear UI.
   Dynamic values are placed with textContent; no path or upstream title becomes HTML. */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  const fmtBytes = n => {
    n = Number(n || 0);
    if (n < 1024) return n + ' B';
    const units = ['KB', 'MB', 'GB', 'TB'];
    let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < units.length - 1);
    return (n >= 10 ? n.toFixed(1) : n.toFixed(2)) + ' ' + units[i];
  };
  async function api(path, body, allowPartial = false) {
    const response = await fetch(path, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    });
    const data = await response.json().catch(() => ({}));
    if (allowPartial && response.status === 409 && Array.isArray(data.receipts)
        && Number.isInteger(data.deleted) && Number.isInteger(data.count)) return data;
    if (!response.ok || data.ok === false) throw new Error(data.error || data.detail || ('HTTP ' + response.status));
    return data;
  }
  function dialog() { return $('storage-dlg'); }
  function body() { return $('storage-body'); }
  function setNote(text) { const n = $('storage-note'); if (n) n.textContent = text; }
  function show() { const d = dialog(); if (d && !d.open) d.showModal(); }
  function errorView(error, retry) {
    const host = body(); host.replaceChildren();
    host.append(el('div', 'storage-group storage-error', error && error.message || error));
    if (retry) { const row = el('div', 'storage-actions'); const b = el('button', '', 'Try again');
      b.onclick = retry; row.append(b); host.append(row); }
  }

  let optionalTimer = 0;
  let viewVersion = 0;
  function endView() { clearTimeout(optionalTimer); optionalTimer = 0; viewVersion++; }
  function beginView() {
    endView(); show();
    const version = viewVersion;
    return () => version === viewVersion && !!dialog()?.open;
  }
  dialog()?.addEventListener('close', endView);
  function section(title, note) {
    const group = el('section', 'storage-group');
    group.append(el('div', 'storage-name', title));
    if (note) group.append(el('div', 'storage-meta', note));
    return group;
  }

  function jobView(job) {
    const group = section('Installation activity', job.running
      ? 'Installing ' + (job.current || 'the first selected tool') + '… Keep MOT Deck open.'
      : 'The most recent optional-install receipts are retained until the next install.');
    for (const receipt of job.receipts || []) {
      const row = el('div', 'storage-row');
      row.append(el('div', 'storage-name', receipt.label || receipt.id));
      row.append(el('div', receipt.ok ? 'storage-preserve' : 'storage-error',
        receipt.ok ? 'Installed and verified from disk' : 'Install failed · ' + (receipt.tail || 'see install log')));
      row.append(el('div', 'storage-meta', receipt.seconds + 's'));
      group.append(row);
    }
    return group;
  }

  function optionalView(data, current) {
    const group = section('Add optional tools',
      'Core is always MOT Deck, runner, Hermes, Odysseus, SearXNG, API and Capabilities. Select only the additional local tools you want.');
    const selected = new Set();
    for (const row of data.options || []) {
      const line = el('label', 'storage-row storage-choice');
      const name = el('div', 'storage-name');
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = row.id;
      check.disabled = !!row.installed || !!(data.job && data.job.running);
      check.addEventListener('change', () => {
        check.checked ? selected.add(row.id) : selected.delete(row.id);
        install.disabled = !selected.size || !!(data.job && data.job.running);
      });
      name.append(check, document.createTextNode(' ' + row.label));
      line.append(name);
      const meta = el('div', 'storage-meta', row.installed ? 'Installed' : row.note);
      if ((row.requires || []).length) meta.append(document.createElement('br'),
        document.createTextNode('Also installs: ' + row.requires.join(', ')));
      line.append(meta, el('div', row.installed ? 'storage-preserve' : '', row.installed ? 'Ready' : 'Optional'));
      group.append(line);
    }
    const actions = el('div', 'storage-actions');
    const install = el('button', 'primary', data.job && data.job.running ? 'Installation running…' : 'Install selected');
    install.disabled = true; // enabled only by a non-empty eligible selection
    install.onclick = async () => {
      install.disabled = true; install.textContent = 'Starting…';
      try {
        await api('/api/storage/optional/install', {ids:Array.from(selected)});
        if (current()) inventory();
      } catch (e) { if (current()) errorView(e, () => inventory()); }
    };
    actions.append(install); group.append(actions);
    return group;
  }

  function resetView(capability) {
    capability = capability || {};
    const group = section('Fresh start or uninstall',
      'These are broader than component removal. Both require a second exact preview and move only proven targets to Trash.');
    const row = el('div', 'storage-row');
    row.append(el('div', 'storage-name', 'Factory reset'));
    row.append(el('div', 'storage-meta', 'Erase MOT Deck’s canonical local data and runtime state, then reopen a fresh core setup. External/shared stores remain.'));
    const reset = el('button', 'danger', capability.factory_reset ? 'Preview reset…' : 'Reset unavailable');
    reset.disabled = !capability.factory_reset;
    reset.onclick = () => resetPreview('factory-reset');
    row.append(reset); group.append(row);
    if (!capability.factory_reset && capability.reason)
      group.append(el('div', 'storage-warn', 'Factory reset unavailable: ' + capability.reason));
    const uninstallRow = el('div', 'storage-row');
    uninstallRow.append(el('div', 'storage-name', 'Uninstall MOT Deck'));
    uninstallRow.append(el('div', 'storage-meta', 'Move the verified app bundle and canonical Application Support root to Trash. Repositories and external/shared stores remain.'));
    const uninstall = el('button', 'danger', 'Preview full uninstall…'); uninstall.onclick = () => resetPreview('full-uninstall');
    uninstallRow.append(uninstall); group.append(uninstallRow);
    return group;
  }

  async function inventory(focus) {
    const current = beginView();
    setNote('Runtime removal preserves histories, settings, workspaces, documents, outputs and model weights.');
    body().replaceChildren(el('div', 'cs-empty', 'Reading exact install paths…'));
    try {
      const [data, optional] = await Promise.all([api('/api/storage/runtimes'), api('/api/storage/optional')]);
      if (!current()) return;
      const group = section('Installed component runtimes',
        'Removing a runtime keeps its histories, settings, workspaces, documents, outputs and model weights.');
      for (const row of data.runtimes || []) {
        const line = el('div', 'storage-row'); line.dataset.target = row.id;
        line.append(el('div', 'storage-name', row.label));
        const meta = el('div', 'storage-meta');
        meta.append(document.createTextNode(row.installed ? 'Runtime installed' : 'Runtime not installed'));
        if (row.note) meta.append(document.createElement('br'), document.createTextNode(row.note));
        line.append(meta);
        const action = el('button', row.installed ? 'danger' : '', row.installed ? 'Uninstall…' : 'Not installed');
        action.disabled = !row.installed;
        action.onclick = () => runtimePreview(row.id);
        const actions = el('div', 'storage-row-actions');
        if (row.installed) {
          const idleBtn = el('button', 'storage-idle-btn');
          const policies = ['auto', 'awake', 'sleep'];
          const labels = {
            'auto': 'Idle: Auto',
            'awake': 'Idle: Always Awake',
            'sleep': 'Idle: Sleep when Hidden'
          };
          const titles = {
            'auto': 'Auto — sleeps when hidden for > 15 minutes or memory pressure is elevated',
            'awake': 'Always Awake — stays resident in background; never suspended',
            'sleep': 'Sleep when Hidden — frees webview memory as soon as you switch away'
          };
          let curPolicy = row.idle_policy || (data.idle_prefs && data.idle_prefs[row.id]) || 'auto';
          const updateBtn = (pol) => {
            curPolicy = pol;
            idleBtn.textContent = labels[pol] || 'Idle: Auto';
            idleBtn.title = titles[pol] || '';
            idleBtn.dataset.policy = pol;
          };
          updateBtn(curPolicy);
          idleBtn.onclick = async (e) => {
            e.stopPropagation();
            const nextIndex = (policies.indexOf(curPolicy) + 1) % policies.length;
            const nextPol = policies[nextIndex];
            updateBtn(nextPol);
            try {
              await api('/api/storage/idle_prefs', { id: row.id, policy: nextPol });
            } catch (err) {
              console.error('Failed to update idle preference', err);
            }
          };
          actions.append(idleBtn);
        }
        actions.append(action);
        line.append(actions);
        group.append(line);
      }
      const sections = [group, optionalView(optional, current), resetView(data.reset)];
      if ((optional.job || {}).running || (optional.job || {}).receipts?.length) sections.splice(2, 0, jobView(optional.job));
      body().replaceChildren(...sections);
      clearTimeout(optionalTimer);
      if ((optional.job || {}).running) optionalTimer = setTimeout(() => { if (current()) inventory(focus); }, 1500);
      if (focus) {
        const row = Array.from(body().querySelectorAll('[data-target]')).find(node => node.dataset.target === focus);
        if (row) { row.scrollIntoView({block:'center'}); row.style.borderColor = 'var(--gold)'; }
      }
    } catch (e) { if (current()) errorView(e, () => inventory(focus)); }
  }

  async function runtimePreview(target) {
    const current = beginView();
    setNote('Review the exact runtime removal. Nothing below includes user data or model weights.');
    body().replaceChildren(el('div', 'cs-empty', 'Building ownership preview…'));
    try {
      const plan = await api('/api/storage/runtime/plan', {target});
      if (!current()) return;
      const group = el('div', 'storage-group');
      group.append(el('div', 'storage-name', 'Uninstall ' + plan.label));
      group.append(el('div', 'storage-meta', fmtBytes(plan.bytes) + ' moves to Trash · space returns only after Trash is emptied'));
      const paths = el('div', 'storage-paths');
      for (const row of plan.paths || []) paths.append(el('div', '', (row.state === 'present' ? 'MOVE  ' : 'ABSENT  ') + row.path));
      group.append(paths);
      const keep = el('div', 'storage-preserve', 'Preserved: ' + (plan.preserve || []).join(' · ')); group.append(keep);
      if (plan.note) group.append(el('div', 'storage-warn', plan.note));
      const actions = el('div', 'storage-actions');
      const back = el('button', '', 'Back'); back.onclick = () => inventory(target);
      const apply = el('button', 'danger primary', 'Move runtime to Trash');
      apply.onclick = async () => {
        apply.disabled = true; apply.textContent = 'Removing…';
        try {
          const result = await api('/api/storage/runtime/apply', {token: plan.token});
          if (!current()) return;
          group.replaceChildren(el('div', 'storage-name', plan.label + ' runtime removed'));
          group.append(el('div', 'storage-meta', result.moved
            ? 'Moved to ' + result.trash + '. User data was preserved.'
            : 'The runtime was already absent; install state was reconciled.'));
          const done = el('div', 'storage-actions'); const close = el('button', '', 'Done');
          close.onclick = () => { closeStorageManager(); if (typeof refresh === 'function') refresh(true); };
          done.append(close); group.append(done);
        } catch (e) { if (current()) errorView(e, () => runtimePreview(target)); }
      };
      actions.append(back, apply); group.append(actions); body().replaceChildren(group);
    } catch (e) { if (current()) errorView(e, () => inventory(target)); }
  }

  async function clearPreview(lane) {
    const current = beginView();
    setNote('Conversation deletion uses the lane’s supported API. It cannot be undone.');
    body().replaceChildren(el('div', 'cs-empty', 'Reading current conversations…'));
    try {
      const plan = await api('/api/storage/chats/plan', {lane});
      if (!current()) return;
      const group = el('div', 'storage-group');
      group.append(el('div', 'storage-name', 'Delete all ' + (lane === 'hermes' ? 'Hermes' : 'Chat / Agent') + ' chats'));
      group.append(el('div', 'storage-meta', plan.count + ' conversation' + (plan.count === 1 ? '' : 's') + ' currently stored'));
      group.append(el('div', 'storage-warn', plan.note));
      const actions = el('div', 'storage-actions');
      const cancel = el('button', '', 'Cancel'); cancel.onclick = closeStorageManager;
      const apply = el('button', 'danger primary', plan.count ? 'Delete ' + plan.count + ' chats' : 'Nothing to delete');
      apply.disabled = !plan.count;
      apply.onclick = async () => {
        apply.disabled = true; apply.textContent = 'Deleting…';
        try {
          const result = await api('/api/storage/chats/apply', {token: plan.token}, true);
          if (!current()) return;
          group.replaceChildren(el('div', 'storage-name', result.deleted + ' of ' + result.count + ' chats deleted'));
          const failed = (result.receipts || []).filter(row => !row.ok);
          if (failed.length) group.append(el('div', 'storage-error', failed.map(row => row.id + ': ' + row.detail).join('\n')));
          const done = el('div', 'storage-actions'); const close = el('button', '', 'Done');
          close.onclick = () => { closeStorageManager(); if (typeof initChat === 'function') initChat(); };
          done.append(close); group.append(done);
        } catch (e) { if (current()) errorView(e, () => clearPreview(lane)); }
      };
      actions.append(cancel, apply); group.append(actions); body().replaceChildren(group);
    } catch (e) { if (current()) errorView(e); }
  }

  async function resetPreview(mode) {
    const current = beginView();
    setNote('This is the broadest local-data operation. Review every target and preserved boundary.');
    body().replaceChildren(el('div', 'cs-empty', 'Verifying the installed app and canonical data root…'));
    try {
      const plan = await api('/api/storage/reset/plan', {mode});
      if (!current()) return;
      const size = plan.bytes === null || plan.bytes === undefined
        ? (plan.size_note || 'Size is not scanned while the app is running.')
        : fmtBytes(plan.bytes) + ' moves to Trash';
      const group = section(plan.label, size + ' · no target is permanently erased by this action');
      const paths = el('div', 'storage-paths');
      for (const path of plan.moves || []) paths.append(el('div', '', 'MOVE  ' + path));
      group.append(paths);
      group.append(el('div', 'storage-preserve', 'Preserved: ' + (plan.preserve || []).join(' · ')));
      if ((plan.running || []).length) group.append(el('div', 'storage-warn',
        'Owned processes that will stop first: ' + plan.running.join(', ')));
      group.append(el('div', 'storage-warn', plan.note));
      const phrase = mode === 'factory-reset' ? 'RESET' : 'UNINSTALL';
      const confirm = document.createElement('input'); confirm.className = 'storage-confirm';
      confirm.placeholder = 'Type ' + phrase; confirm.autocomplete = 'off'; confirm.spellcheck = false;
      group.append(confirm);
      const actions = el('div', 'storage-actions');
      const back = el('button', '', 'Back'); back.onclick = () => inventory();
      const apply = el('button', 'danger primary', mode === 'factory-reset' ? 'Reset and reopen' : 'Uninstall MOT Deck');
      apply.disabled = true;
      confirm.addEventListener('input', () => { apply.disabled = confirm.value !== phrase; });
      apply.onclick = async () => {
        apply.disabled = true; apply.textContent = 'Stopping owned services…';
        try {
          const result = await api('/api/storage/reset/apply', {token:plan.token});
          if (!current()) return;
          group.replaceChildren(el('div', 'storage-name', result.message),
            el('div', 'storage-meta', 'This window will close. The recovery receipt is ' + result.log));
        } catch (e) { if (current()) errorView(e, () => resetPreview(mode)); }
      };
      actions.append(back, apply); group.append(actions); body().replaceChildren(group); confirm.focus();
    } catch (e) { if (current()) errorView(e, () => inventory()); }
  }

  window.openStorageManager = focus => inventory(String(focus || ''));
  window.closeStorageManager = () => { endView(); const d = dialog(); if (d && d.open) d.close(); };
  window.toggleChatMenu = event => {
    event.stopPropagation(); const menu = $('chat-menu'), button = $('cs-more');
    const opening = menu.hidden; menu.hidden = !opening; button.setAttribute('aria-expanded', opening ? 'true' : 'false');
    if (opening) { const r = button.getBoundingClientRect(); menu.style.left = Math.max(8, r.right - 210) + 'px'; menu.style.top = (r.bottom + 5) + 'px'; }
  };
  window.refreshChatSessions = () => {
    const menu = $('chat-menu'); if (menu) menu.hidden = true;
    const button = $('cs-more'); if (button) button.setAttribute('aria-expanded', 'false');
    if (typeof loadSessions === 'function') loadSessions();
  };
  window.planClearLaneChats = () => {
    refreshChatSessions();
    const lane = (typeof chatPane !== 'undefined' && chatPane.mode === 'hermes') ? 'hermes' : 'odysseus';
    clearPreview(lane);
  };
  document.addEventListener('click', event => {
    const menu = $('chat-menu'); const button = $('cs-more');
    if (menu && !menu.hidden && !menu.contains(event.target) && event.target !== button) {
      menu.hidden = true; if (button) button.setAttribute('aria-expanded', 'false');
    }
  });
})();
