#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const shared = fs.existsSync('/usr/local/lib/sima-sdk/components.js')
  ? '/usr/local/lib/sima-sdk/components.js' : '../vscode-extension/src/components';
const { validateCatalog, downloadArtifact } = require(shared);
async function main() {
  const [command, manifest = path.join(__dirname, '../components.json'), sdk] = process.argv.slice(2);
  const catalog = validateCatalog(JSON.parse(fs.readFileSync(manifest, 'utf8')));
  if (command === 'validate') { console.log('SDK component manifest is valid'); return; }
  if (command === 'check-release') {
    const release = /^v?(\d+\.\d+\.\d+(?:\.\d+)?)$/.exec(sdk || '')?.[1];
    if (!release) return; // Development image identity is never treated as a qualified SDK release.
    const selected = catalog.sdks[catalog.build_sdk_version];
    if (!selected.sdk_releases.includes(release) || selected.status !== 'qualified')
      throw Error('Tagged SDK releases require a qualified matching component cohort');
    console.log(`Qualified component cohort matches SDK ${release}`);
    return;
  }
  const row = catalog.sdks[sdk || catalog.build_sdk_version];
  if (!row || row.status === 'revoked') throw Error('No build-compatible Codex CLI component');
  const cli = row.components['codex-cli'];
  if (command === 'cli-version') { console.log(cli.version); return; }
  if (command !== 'install-cli') throw Error('Expected validate, cli-version, or install-cli');
  const file = await downloadArtifact(cli.artifact, '/tmp/sima-sdk-cli-artifacts', fetch, '.tgz');
  const contents = spawnSync('tar', ['-xOf', file, 'package/package.json'], { encoding: 'utf8' });
  if (contents.status !== 0) throw Error('Unable to read Codex CLI package metadata');
  const metadata = JSON.parse(contents.stdout);
  if (metadata.name !== cli.package || metadata.version !== cli.version) throw Error('Codex CLI package identity/version mismatch');
  const installed = spawnSync('npm', ['install', '-g', file], { stdio: 'inherit' });
  if (installed.status !== 0) throw Error('Pinned Codex CLI installation failed');
  const result = spawnSync('codex', ['--version'], { encoding: 'utf8' });
  if (result.status !== 0 || result.stdout.trim() !== `codex-cli ${cli.version}`)
    throw Error('Installed Codex CLI version does not match the SDK component manifest');
  fs.rmSync('/tmp/sima-sdk-cli-artifacts', { recursive: true, force: true });
  console.log(`Installed manifest-selected codex-cli ${cli.version}`);
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
