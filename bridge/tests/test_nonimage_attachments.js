/* A2 — non-image attachment contract across the native shell, panel and both
 * supporting backends. Run from the repository root with Node. */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const read = (...parts) => fs.readFileSync(path.join(ROOT, ...parts), 'utf8');
const panel = read('bridge', 'panel', 'index.html');
const files = read('bridge', 'panel', 'assets', 'chat-files.js');
const swift = read('app', 'main.swift');
const hermes = read('bridge', 'routers', 'hermes.py');
const odychat = read('bridge', 'routers', 'odychat.py');
const direct = read('bridge', 'routers', 'chat.py');

let failures = 0;
function check(name, ok) {
  console.log((ok ? 'PASS' : 'FAIL') + ' ' + name);
  if (!ok) failures++;
}

function grab(name) {
  const at = panel.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('missing function ' + name);
  const open = panel.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < panel.length; i++) {
    if (panel[i] === '{') depth++;
    if (panel[i] === '}' && --depth === 0) return panel.slice(at, i + 1);
  }
  throw new Error('unbalanced function ' + name);
}

function element(tag) {
  return {tagName:String(tag).toUpperCase(), children:[], attributes:{},
    appendChild(child){ this.children.push(child); },
    setAttribute(k,v){ this.attributes[k] = v; }, remove(){ this.removed = true; }};
}

const assetAt = panel.indexOf('<script src="/assets/chat-files.js"></script>');
const mainAt = panel.indexOf('<script>\nconst dlg');
check('the file helper is loaded before the main inline panel program',
      assetAt >= 0 && mainAt >= 0 && assetAt < mainAt);
check('the visible picker lists every supported document suffix',
      ['.txt','.md','.csv','.json','.py','.js','.html','.pdf']
        .every(ext => panel.includes('accept="image/png,image/jpeg,image/webp')
          && panel.includes(ext)));
check('the composer still stages exactly one attachment object',
      panel.includes('attachedImage: null') && !panel.includes('attachedFiles:'));
check('Direct Chat refuses files before clearing or posting the composer',
      /mode === 'chat'[\s\S]{0,180}?attachedImage\.kind === 'file'[\s\S]{0,180}?direct Chat accepts images only/.test(panel));
check('the Direct backend independently refuses a file instead of dropping it',
      /if body\.get\("file"\)[\s\S]{0,500}?direct Chat accepts images only/.test(direct));
check('Agent and Hermes use the same typed file payload',
      /file:img\.data, file_name:img\.name, file_mime:img\.mime/.test(panel)
      && (panel.match(/\.\.\.attachPayload/g) || []).length === 2);
check('file names render as text, never markup',
      /nm\.textContent = name/.test(files) && !/innerHTML\s*=\s*name/.test(files));
check('live data attachments are inert; only first-party API routes become links',
      /startsWith\('\/api\/'\)/.test(panel)
      && /createElement\('span'\); th\.title = 'File attached'/.test(panel));
const attachLineEl = new Function('document', 'showImageLightbox',
  grab('attachLineEl') + '; return attachLineEl;')({createElement:element}, () => {});
const liveRow = attachLineEl('data:text/html;base64,PGgxPng8L2gxPg==', 'page.html', null, '', 'file');
const savedRow = attachLineEl('/api/ody/attachment/up_1', 'notes.txt', null, '', 'file');
check('the rendered live HTML/JS file marker is behaviorally non-navigable',
      liveRow.children[0].tagName === 'SPAN' && !liveRow.children[0].href);
check('a persisted first-party attachment is behaviorally rendered as a download',
      savedRow.children[0].tagName === 'A'
      && savedRow.children[0].href === '/api/ody/attachment/up_1'
      && savedRow.children[0].download === 'notes.txt');
check('the native file hook preserves the Direct Chat refusal',
      /motdeckNativeFileDrop[\s\S]{0,180}?mode === 'chat'/.test(files));
check('the native file hook enforces the same 10 MiB ceiling',
      /10 \* 1024 \* 1024/.test(files));
check('picker, browser drop and clipboard paste all share one file/image classifier',
      /function acceptImageFile/.test(panel)
      && (panel.match(/acceptImageFile\(file\)/g) || []).length >= 2
      && /if \(f\) acceptImageFile\(f\)/.test(panel));
check('Agent can open the picker for documents even when its image path is unavailable',
      /if \(!v\.on && chatPane\.mode === 'chat'\)/.test(panel)
      && /const usable = v\.on \|\| filesWork/.test(panel));
check('the Swift drop surface recognizes supported documents separately from audio and images',
      /let fileMimes =/.test(swift)
      && /motdeckNativeFileDrop/.test(swift)
      && /isAudio \? "motdeckNativeAudioDrop" : \(isFile \? "motdeckNativeFileDrop"/.test(swift));
check('Hermes uses native file.attach and pdf.attach operations',
      /stage_hermes_attachment/.test(hermes)
      && /file\.attach/.test(read('bridge', 'core', 'chatattachments.py'))
      && /pdf\.attach/.test(read('bridge', 'core', 'chatattachments.py')));
check('Odysseus receives files through its native upload endpoint',
      /\/api\/upload/.test(odychat) && /attachments/.test(odychat));

if (failures) {
  console.error(`\n${failures} non-image attachment contract(s) failed`);
  process.exit(1);
}
console.log('\nall non-image attachment contracts passed');
