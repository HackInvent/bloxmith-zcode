/** Feed a private stdin prompt to the official CLI without patching its files.
 * Only process-local argv changes; user settings and credentials stay untouched.
 */
'use strict';
const fs = require('node:fs');
const entry = process.argv[2];
try {
  const chunks = [];
  let size = 0;
  const buffer = Buffer.alloc(65536);
  for (;;) {
    const count = fs.readSync(0, buffer, 0, buffer.length, null);
    if (!count) break;
    size += count;
    if (size > 8 * 1024 * 1024) throw new Error('Prompt envelope is too large.');
    chunks.push(Buffer.from(buffer.subarray(0, count)));
  }
  const packet = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (typeof packet.prompt !== 'string' || !packet.prompt.trim()) throw new Error('Missing prompt.');
  process.argv = [process.execPath, entry, ...process.argv.slice(3), '--prompt', packet.prompt];
  require(entry);
} catch {
  process.stderr.write('Zcode engine could not be started. Check the engine script and Node runtime.\n');
  process.exitCode = 1;
}
