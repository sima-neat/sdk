// Shared runtime resolver for the SDK shell interface and code-server wrapper.
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { ComponentCatalog, IDS, ARCHES } = require(
  require('node:fs').existsSync('/usr/local/lib/sima-sdk/components.js')
    ? '/usr/local/lib/sima-sdk/components.js' : '../vscode-extension/src/components');
const UPSTREAM = '/opt/code-server/bin/code-server-upstream';
function createComponentService({ extensionsDir, spawn = spawnSync, Catalog = ComponentCatalog } = {}) {
  const version = spawn(UPSTREAM, ['--config', '/dev/null', '--version'], { encoding: 'utf8' });
  if (version.status !== 0) throw Error('Unable to detect code-server engine');
  const codeServer = version.stdout.trim().split(/\s+/)[0];
  const vscodeVersion = /with Code (\d+\.\d+\.\d+)/.exec(version.stdout)?.[1];
  if (!vscodeVersion) throw Error('Unable to detect VS Code engine');
  return new Catalog({ globalStorageUri: { fsPath: path.join(os.homedir(), '.local/share/sima-sdk/components') },
    extensionPath: '/usr/local/share/sima-sdk' }, { codeServer, vscodeVersion,
    profileFile: path.join(extensionsDir || path.join(os.homedir(), '.local/share/code-server/extensions'), 'extensions.json') });
}
async function resolveComponents(service) {
  const state = await service.refresh();
  if (!state.available) throw Error(state.error);
  return { schema_version: 1, available: true, sdk_release: state.sdkRelease,
    cohort: state.sdkVersion, status: state.status, source: state.source,
    architecture: ARCHES[process.arch], code_server: service.options.codeServer,
    vscode: service.options.vscodeVersion,
    extensions: Object.fromEntries(Object.values(IDS).map(id => {
      const target = Object.values(state.components).find(component => component.id === id);
      return [id, target.version];
    })) };
}
module.exports = { createComponentService, resolveComponents };
