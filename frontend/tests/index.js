// Entry shim for `node --test frontend/tests/`.
// On Node >= 23 the test runner treats a bare directory argument as a file
// path (glob expansion was removed for trailing-slash directory args), so the
// runner spawns this directory as an entry point. This file (the CJS directory
// index) then imports every *.test.mjs itself; node:test reports through the
// normal channels and failures propagate via the process exit code.
// Alternative invocations that also work: `node --test` from frontend/,
// or `node --test frontend/tests/*.test.mjs`.
(async () => {
  const { readdirSync } = require('node:fs');
  const { join } = require('node:path');
  const { pathToFileURL } = require('node:url');

  const here = __dirname;
  const files = readdirSync(here).filter((n) => n.endsWith('.test.mjs')).sort();
  if (files.length === 0) {
    console.error('No *.test.mjs files found in ' + here);
    process.exit(1);
  }
  for (const name of files) {
    await import(pathToFileURL(join(here, name)).href);
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
