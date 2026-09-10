'use strict';
const vm = require('node:vm');

// Compile candidate endings instead of duplicating production functions or writing
// a JavaScript lexer that mishandles comments, regexes and template literals.
function extractFunction(source, name) {
  if (!/^[A-Za-z_$][\w$]*$/.test(name)) throw new Error('invalid function name');
  const match = new RegExp('^(?:async )?function ' + name.replace(/\$/g, '\\$') + '\\s*\\(', 'm').exec(source);
  if (!match) throw new Error('missing function: ' + name);
  for (let end = source.indexOf('}', match.index); end >= 0; end = source.indexOf('}', end + 1)) {
    const candidate = source.slice(match.index, end + 1);
    try {
      new vm.Script(candidate);
      new Function(candidate);
      return candidate;
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
  }
  throw new Error('unterminated function: ' + name);
}
module.exports = {extractFunction};
