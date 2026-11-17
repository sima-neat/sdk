const fs = require('fs/promises');

function supportsModelRegistry(release) {
  // Platform version is independent of the Neat extension and CLI versions.
  for (const key of ['Platform Base', 'Platform Version', 'SDK Version']) {
    const line = release.split(/\r?\n/).find(line => line.split('=')[0].trim() === key);
    if (!line) continue;
    const version = line.slice(line.indexOf('=') + 1).trim();
    const match = /^(\d+)\.(\d+)(?:\.(\d+))?(?=$|[~+_\-])/.exec(version);
    return !!match && Number(match[1]) >= 3;
  }
  return false;
}

async function modelRegistryAvailable(readFile = fs.readFile) {
  try {
    return supportsModelRegistry(await readFile('/etc/sdk-release', 'utf8'));
  } catch {
    return false;
  }
}

module.exports = {supportsModelRegistry, modelRegistryAvailable};
