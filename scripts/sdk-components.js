#!/usr/bin/env node
// Versioned SDK-owned setup interface. JSON stdout is reserved for the result.
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { createComponentService, resolveComponents } = require('/usr/local/lib/sima-sdk/component-service.js');
async function main() {
  const args = process.argv.slice(2);
  if (args.length === 2 && args[0] === 'resolve' && args[1] === '--json') {
    console.log(JSON.stringify(await resolveComponents(createComponentService())));
    return;
  }
  // Explicit expected versions prevent a changed catalog silently installing a
  // different cohort between setup's resolve and install operations.
  if (args.length !== 6 || args[0] !== 'install' || args[1] !== '--json' ||
      args[2] !== '--extension' || args[4] !== '--extensions-dir' ||
      !/^(openai\.chatgpt|anthropic\.claude-code)@\d+\.\d+\.\d+(?:\.\d+)?$/.test(args[3]) ||
      !path.isAbsolute(args[5]))
    throw Error('Usage: sdk-components resolve --json | install --json --extension ID@VERSION --extensions-dir /absolute/path');
  const result = spawnSync('/opt/code-server/bin/code-server',
    ['--extensions-dir', args[5], '--install-extension', args[3], '--force'], { encoding: 'utf8' });
  if (result.stdout) process.stderr.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) throw Error('SDK component installation failed' + (result.error ? ': ' + result.error.message : ''));
  console.log(JSON.stringify({ schema_version: 1, installed: true, extension: args[3] }));
}
main().catch(error => {
  console.log(JSON.stringify({ schema_version: 1, available: false, error: error.message }));
  process.exitCode = 1;
});
