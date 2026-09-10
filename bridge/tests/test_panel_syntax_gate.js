'use strict';
/**
 * test_panel_syntax_gate.js
 *
 * RIGOROUS SYNTAX GATE FOR ALL WEB ASSETS
 *
 * Verifies that:
 * 1. bridge/panel/index.html has zero JavaScript syntax errors in all inline <script> tags.
 * 2. Every HTML file under bridge/panel/ has valid <script> blocks.
 * 3. Every .js file in bridge/panel/assets and subdirectories is valid JavaScript.
 *
 * If ANY syntax error is found (e.g. missing brace, unclosed string, malformed token),
 * this test fails with exit code 1 and prints the exact error, line, and file.
 */

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '../..');
const PANEL_DIR = path.join(ROOT, 'bridge', 'panel');

let totalChecks = 0;
let failures = 0;

function checkScriptCode(code, sourceName) {
  totalChecks++;
  try {
    new vm.Script(code, { filename: sourceName });
  } catch (err) {
    failures++;
    console.error(`\n[SYNTAX ERROR] ${sourceName}:`);
    console.error(err.message);
    if (err.stack) {
      console.error(err.stack.split('\n').slice(0, 4).join('\n'));
    }
  }
}

function checkHtmlFile(filePath) {
  const rel = path.relative(ROOT, filePath);
  const content = fs.readFileSync(filePath, 'utf8');
  const scriptRegex = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  let match;
  let scriptIndex = 0;
  while ((match = scriptRegex.exec(content)) !== null) {
    const attrs = match[1];
    const code = match[2];
    // Skip importmap or non-JS types if any
    if (/type\s*=\s*["'](?:application\/ld\+json|importmap)["']/i.test(attrs)) {
      continue;
    }
    // If src is specified and body is empty, skip
    if (!code.trim() && /src\s*=/i.test(attrs)) {
      continue;
    }
    scriptIndex++;
    checkScriptCode(code, `${rel}#script-${scriptIndex}`);
  }
}

function checkJsFile(filePath) {
  const rel = path.relative(ROOT, filePath);
  const code = fs.readFileSync(filePath, 'utf8');
  checkScriptCode(code, rel);
}

function walkDir(dir) {
  if (!fs.existsSync(dir)) return;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'vendor' || entry.name === '.git') continue;
      walkDir(full);
    } else if (entry.isFile()) {
      if (entry.name.endsWith('.html')) {
        checkHtmlFile(full);
      } else if (entry.name.endsWith('.js') && !entry.name.endsWith('.min.js')) {
        checkJsFile(full);
      }
    }
  }
}

console.log(`[syntax-gate] Scanning web assets in ${path.relative(ROOT, PANEL_DIR)}...`);
walkDir(PANEL_DIR);

console.log(`[syntax-gate] Evaluated ${totalChecks} JavaScript units.`);
if (failures > 0) {
  console.error(`\n[syntax-gate] FAILED: ${failures} syntax error(s) found! Refusing build.`);
  process.exit(1);
} else {
  console.log(`[syntax-gate] PASSED: All ${totalChecks} JavaScript units are 100% syntactically valid.`);
}
