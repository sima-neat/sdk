#!/usr/bin/env node
// Preserve the upstream CLI contract while routing SDK-managed agents through qualification.
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { ComponentCatalog, IDS } = require('/usr/local/lib/sima-sdk/components.js');
const upstream = '/opt/code-server/bin/code-server-upstream';
async function main() {
  const args = process.argv.slice(2), targets = [];
  let service;
  for (let i = 0; i < args.length; i++) {
    const joined = args[i].startsWith('--install-extension=');
    if (!joined && args[i] !== '--install-extension') continue;
    const index = joined ? i : ++i;
    const requested = joined ? args[index].slice('--install-extension='.length) : args[index];
    const key = Object.keys(IDS).find(key => requested?.split('@')[0].toLowerCase() === IDS[key]);
    if (!key) continue;
    if (!service) {
      const version = spawnSync(upstream, ['--config', '/dev/null', '--version'], { encoding: 'utf8' });
      if (version.status !== 0) throw Error('Unable to detect code-server engine');
      const codeServer = version.stdout.trim().split(/\s+/)[0];
      const vscodeVersion = /with Code (\d+\.\d+\.\d+)/.exec(version.stdout)?.[1];
      service = new ComponentCatalog({ globalStorageUri: {fsPath: path.join(os.homedir(), '.local/share/sima-sdk/components')},
        extensionPath: '/usr/local/share/sima-sdk' }, { codeServer, vscodeVersion });
    }
    const state = await service.refresh();
    if (!state.available) throw Error(state.error);
    const target = state.components[key];
    if (requested.includes('@') && requested.split('@')[1] !== target.version)
      throw Error(`SDK ${state.sdkVersion} requires ${target.id}@${target.version}; requested version is not qualified`);
    const prepared = await service.artifact(key);
    if (prepared.target.version !== target.version) throw Error("Component qualification changed; retry installation");
    args[index] = joined ? '--install-extension=' + prepared.file : prepared.file;
    targets.push(target);
  }
  if (targets.length && !args.includes('--force')) args.push('--force');
  const result = spawnSync(upstream, args, { stdio: 'inherit' });
  if (result.status !== 0) { process.exitCode = result.status || 1; return; }
  if (targets.length) {
    const index = args.indexOf('--extensions-dir');
    const dir = index >= 0 ? args.slice(index, index + 2) : args.filter(a=>a.startsWith('--extensions-dir='));
    const listing = spawnSync(upstream, ['--config', '/dev/null', ...dir, '--list-extensions', '--show-versions'], {encoding:'utf8'});
    const installed = listing.stdout?.toLowerCase().split(/\r?\n/) || [];
    if (listing.status !== 0 || targets.some(target=>!installed.includes(`${target.id}@${target.version}`)))
      throw Error('Installed agent version does not match the SDK component manifest');
  }
}
main().catch(error => { console.error('SDK component installation blocked: ' + error.message); process.exitCode = 1; });
