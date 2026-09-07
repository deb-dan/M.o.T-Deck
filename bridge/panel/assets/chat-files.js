/* A2 — the non-image half of the one-slot Chat composer attachment surface.
   Loaded before the main panel script; globals are resolved when these functions are
   invoked, after chatPane/attachNote/clearImage have been initialized. */
function showAttachedFile(dataUrl, name, mime){
  chatPane.attachedImage = {data:dataUrl, name:name,
    mime:mime || 'application/octet-stream', kind:'file'};
  const strip = document.getElementById('chat-attachstrip');
  strip.innerHTML = '';
  const icon = document.createElement('span');
  icon.textContent = '▤'; icon.setAttribute('aria-hidden','true');
  const nm = document.createElement('span');
  nm.className = 'afile'; nm.textContent = name;
  const x = document.createElement('button');
  x.className = 'aclear'; x.textContent = '✕'; x.title = 'Remove this file';
  x.setAttribute('aria-label', x.title); x.onclick = clearImage;
  strip.appendChild(icon); strip.appendChild(nm); strip.appendChild(x);
  strip.hidden = false;
}

window.motdeckNativeFileDrop = function(name, dataUrl, mime){
  if (chatPane.mode === 'chat'){
    attachNote('files work in Agent or Hermes; direct Chat accepts images only');
    return;
  }
  const b64 = (String(dataUrl || '').split(',')[1] || '').replace(/\s/g, '');
  if (!b64){ attachNote('could not read that file'); return; }
  const padding = b64.endsWith('==') ? 2 : (b64.endsWith('=') ? 1 : 0);
  const decodedBytes = Math.floor(b64.length * 3 / 4) - padding;
  if (decodedBytes > 10 * 1024 * 1024){
    attachNote('file too large (max 10 MB)'); return;
  }
  showAttachedFile(dataUrl, name || 'file', mime || 'application/octet-stream');
};
