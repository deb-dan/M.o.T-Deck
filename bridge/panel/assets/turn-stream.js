/* Bridge-owned Chat/Agent transport and the one shared SSE renderer.
   Loaded before the main panel script; every global it calls is resolved only when a
   user starts or resumes a turn, after the panel has finished booting. */
(function () {
  'use strict';
  let requestCounter = 0;

  function requestId(){
    requestCounter += 1;
    return 'panel-' + Date.now().toString(36) + '-' + requestCounter + '-'
      + Math.random().toString(36).slice(2);
  }

  async function jsonFetch(url, options){
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || 'the bridge refused the turn request');
    return data;
  }

  async function create(lane, body){
    return jsonFetch('/api/turns', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(Object.assign({}, body, {lane:lane, request_id:requestId()}))
    });
  }

  async function active(lane, session){
    if (!session) return null;
    const query = '?lane=' + encodeURIComponent(lane) + '&session=' + encodeURIComponent(session);
    const data = await jsonFetch('/api/turns/active' + query);
    return data.turn || null;
  }

  async function metadata(id){
    return jsonFetch('/api/turns/' + encodeURIComponent(id));
  }

  async function stop(turn){
    if (!turn || !turn.id || turn.stopRequested) return null;
    turn.stopRequested = true;
    return jsonFetch('/api/turns/' + encodeURIComponent(turn.id) + '/stop', {method:'POST'});
  }

  function complete(ctx, state, error){
    const turn = ctx.turn, holder = ctx.holder, body = ctx.body, think = ctx.think;
    if (turn.done) return;
    turn.done = true;
    turnStage(state || 'done');
    clearTimeout(turn.timer);
    if (state && state !== 'completed' && error) body.textContent += '\n· ' + error;
    think.remove();
    if (chatPane.curTurn === turn) chatPane.busy = false;
    chatSummary(holder);
    const thought = holder.querySelector('details.think');
    if (thought) thought.open = false;
    holder._raw = body.textContent;
    renderChatBody(body, body.textContent);
    chatToolErrsRedraw(holder);
  }

  function event(ctx, j){
    const turn = ctx.turn, holder = ctx.holder, body = ctx.body, think = ctx.think;
    if (j.type === 'hermes_ping') return;
    if (j.delta === undefined) chatInspect(holder, j);
    if (j.delta !== undefined) {
      turnStage(j.thinking ? 'thinking' : 'answering');
      if (j.thinking) {
        think.hidden = false;
        if (!holder._thinkStart) holder._thinkStart = Date.now();
        let det = holder.querySelector('details.think');
        if (!det) {
          det = document.createElement('details'); det.className = 'think'; det.open = true;
          det.innerHTML = '<summary>thinking</summary><div class="tbody"></div>';
          holder.insertBefore(det, body);
        }
        const tb = det.querySelector('.tbody');
        tb.textContent += j.delta;
        tb.scrollTop = tb.scrollHeight;
      } else {
        think.hidden = true;
        const det = holder.querySelector('details.think');
        if (det && det.open) det.open = false;
        if (det && holder._thinkStart && !holder._thinkDone) {
          holder._thinkDone = true;
          const secs = (Date.now() - holder._thinkStart) / 1000;
          if (secs > 2) {
            const summary = det.querySelector('summary');
            if (summary) summary.textContent = 'thinking · ' + secs.toFixed(1) + 's';
          }
        }
        chatSummary(holder);
        body.textContent += j.delta;
      }
    } else if (j.type === 'model_info' || j.type === 'model_actual') {
      chatPane.model = j.model || chatPane.model;
      holder.querySelector('.who').textContent = liveModelLabel(chatPane.model) || 'Assistant';
    } else if (j.type === 'hermes_session') {
      if (j.id) {
        chatPane.hermesSid = j.id; turn.hermesSid = j.id;
        localStorage.setItem('harness-hermes-sid', j.id);
      }
      if (j.stored_id) {
        chatPane.hermesStoredSid = j.stored_id;
        localStorage.setItem('harness-hermes-stored', j.stored_id);
      }
    } else if (j.type === 'hermes_status') {
      turnStage('prefill (bridge says hermes is working)');
      chatStatus(holder, '▸', j.text || 'hermes is working…');
    } else if (j.type === 'approval') {
      turnStage('awaiting approval');
      chatApproval(holder, j.request || {}, turn.hermesSid);
    } else if (j.type === 'ask') {
      turnStage('awaiting an answer');
      chatAsk(holder, j.request || {}, turn.hermesSid);
    } else if (j.type === 'ask_expire') {
      expireAskCard(holder, String(j.request_id || ''));
    } else if (j.type === 'file_card') {
      const path = String(j.path || '');
      if (path.startsWith('/Users/') || path.startsWith('~')) {
        holder._fileCards = holder._fileCards || new Set();
        if (!holder._fileCards.has(path)) {
          holder._fileCards.add(path);
          try { fileCard(holder, {path:path}); } catch (_) {}
        }
      }
    } else if (j.type === 'guard_flag') {
      const path = String(j.path || '');
      holder._guardFlags = holder._guardFlags || new Set();
      if (path && !holder._guardFlags.has(path)) {
        holder._guardFlags.add(path);
        const line = document.createElement('div'); line.className = 'statusline';
        line.innerHTML = '<span class="r">⚠</span> wrote outside workspace: '
          + '<span class="dim">' + esc(path) + '</span>';
        holder.appendChild(line);
      }
    } else if (j.type === 'tool_start') {
      turnStage('running a tool');
      const raw = j.tool || 'tool';
      const isWeb = /search|web|fetch|browse|url|http/i.test(raw);
      (holder._steps = holder._steps || []).push({tool:raw});
      chatStatus(holder, '▸', isWeb ? 'searching the web…' : ('running ' + raw + '…'));
    } else if (j.type === 'tool_output' || j.type === 'agent_step') {
      if (j.is_error) {
        const tool = String(j.tool || 'tool');
        const why = String(j.error || '').trim();
        const steps = (holder._steps = holder._steps || []);
        const last = steps[steps.length - 1];
        if (last && !last.error) last.error = why || 'refused';
        else steps.push({tool:tool, error:why || 'refused'});
        chatToolErr(holder, tool, why);
        if (holder._summarized) { holder._summarized = false; chatSummary(holder); }
        turnStage('a tool failed');
      } else if (!holder._summarized) {
        chatStatus(holder, '▸', 'reading results…');
      }
    } else if (j.type === 'web_sources') {
      const items = j.data || [];
      const det = document.createElement('details'); det.className = 'sources';
      det.innerHTML = '<summary>' + items.length + ' web sources</summary><div class="slist"></div>';
      const list = det.querySelector('.slist');
      for (const source of items) {
        const url = source.url || source.link || '';
        let host = ''; try { host = new URL(url).hostname.replace('www.',''); } catch (_) {}
        const title = (source.title || host || 'source').slice(0, 60);
        const item = document.createElement('div'); item.className = 'sitem';
        item.innerHTML = '<a href="' + escAttr(url) + '" onclick="openExt(event, this.href)">'
          + esc(title) + '</a><span class="host">' + esc(host) + '</span>';
        list.appendChild(item);
      }
      holder.appendChild(det);
    } else if (j.type === 'vision') {
      if (!holder._visionLine) {
        holder._visionLine = true;
        const line = document.createElement('div'); line.className = 'statusline';
        const model = esc(String(j.model || 'the vision model'));
        if (j.source === 'native')
          line.innerHTML = '<span class="dim">👁</span> the model reads this image directly — '
            + '<span class="dim">' + model + '</span>';
        else if (j.source === 'precaption')
          line.innerHTML = '<span class="dim">👁</span> image described by '
            + '<span class="dim">' + model + '</span> — the agent answers from that description, not from the picture';
        else
          line.innerHTML = '<span class="r">⚠</span> the image was not described here'
            + (j.note ? ': <span class="dim">' + esc(String(j.note)) + '</span>' : '')
            + ' — the agent may not be able to see it';
        holder.appendChild(line);
      }
    } else if (j.type === 'proxy_error') {
      body.textContent += '\n[proxy error: ' + (j.error || '') + ']';
    }
  }

  async function consume(response, ctx){
    if (!response.ok || !response.body) throw new Error('stream refused with HTTP ' + response.status);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const got = await reader.read();
      if (got.done) break;
      ctx.turn.lastByte = Date.now();
      if (ctx.turn.lane === 'hermes') turnArm(TURN_STALL_MS, 'stall');
      buffer += decoder.decode(got.value, {stream:true});
      const frames = buffer.split('\n\n'); buffer = frames.pop();
      for (const frame of frames) {
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6);
          if (payload === '[DONE]') { complete(ctx, 'completed', ''); return; }
          let parsed; try { parsed = JSON.parse(payload); } catch (_) { continue; }
          if (parsed.seq !== undefined) {
            if (parsed.seq <= (ctx.turn.lastSeq || 0)) continue;
            ctx.turn.lastSeq = parsed.seq;
          }
          if (parsed.type === 'terminal') {
            complete(ctx, parsed.state || 'failed', parsed.error || '');
            return;
          }
          event(ctx, parsed);
        }
      }
      scrollChat();
    }
    if (!ctx.turn.detached && !ctx.turn.done)
      throw new Error('the turn stream ended without a completion frame');
  }

  async function recover(record, lane, session){
    if (!record || !record.id || chatPane.busy) return null;
    if (chatPane.mode !== lane || chatPane.sid !== session) return null;
    const holder = addMsg('assistant', '');
    const body = holder.querySelector('.body');
    const think = document.createElement('div');
    think.id = 'thinking'; think.textContent = 'reconnecting…'; think.hidden = false;
    holder.insertBefore(think, body);
    const turn = {id:record.id, lane:lane, stage:'reconnecting',
      ctl:new AbortController(), holder:holder, ended:false, detached:false,
      timer:null, stopArmed:false, lastSeq:0, recovered:true};
    chatPane.curTurn = turn; chatPane.busy = true; sendPaint('Stop');
    const button = document.getElementById('chat-send');
    if (button) { button.title = 'Stop this reply'; button.setAttribute('aria-label', button.title); }
    try {
      const response = await fetch('/api/turns/' + encodeURIComponent(turn.id)
        + '/events?after=0', {signal:turn.ctl.signal});
      await consume(response, {turn:turn, holder:holder, body:body, think:think});
    } catch (error) {
      if (!turn.detached)
        chatStatus(holder, '✓', 'the bridge could not recover this turn — reload to retry');
    } finally {
      clearTimeout(turn.timer);
      if (chatPane.curTurn === turn) {
        chatPane.curTurn = null; chatPane.busy = false; sendPaint('Send');
        if (button) { button.disabled = false; button.title = 'Send message (Enter)';
          button.setAttribute('aria-label', button.title); }
      }
      think.remove();
      scrollChat();
      loadSessions();
    }
    return turn;
  }

  window.HarnessTurnStream = {create:create, active:active, metadata:metadata,
    stop:stop, consume:consume, recover:recover};
}());

function turnHardRelease(turn){
  if (chatPane.curTurn !== turn) return;
  chatPane.curTurn = null;
  chatPane.busy = false;
  const button = document.getElementById('chat-send');
  if (button) { button.disabled = false; sendPaint('Send');
    button.title = 'Send message (Enter)'; button.setAttribute('aria-label', button.title); }
  const thinking = document.getElementById('thinking'); if (thinking) thinking.remove();
}

async function stopTurnNow(reason){
  if (!chatPane.curTurn && !chatPane.busy) return false;
  const turn = chatPane.curTurn;
  if (turn && turn.lane === 'hermes') hermesStop(reason);
  else if (turn && turn.id && window.HarnessTurnStream) {
    try { await HarnessTurnStream.stop(turn); } catch (_) {}
  }
  forceEndTurn(reason);
  if (!chatPane.curTurn && !chatPane.busy) return true;
  await new Promise(resolve => setTimeout(resolve, 80));
  return true;
}

async function detachTurnNow(reason){
  const turn = chatPane.curTurn;
  if (!turn && !chatPane.busy) return false;
  if (turn) {
    turn.detached = true;
    turn.stage = 'detached: ' + reason;
    clearTimeout(turn.timer);
    try { turn.ctl.abort(); } catch (_) {}
    turnHardRelease(turn);
  } else {
    chatPane.busy = false;
    sendPaint('Send');
  }
  return true;
}
