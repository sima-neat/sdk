'use strict';

// "Sign in to SiMa" without a terminal, as extension.js gives it to the Set up SDK page:
// the quiet sima-cli install, the quiet `sima-cli login`, Cancel, the reason shown on
// failure, the signed-in name and email, the latest sima-cli on PyPI, and the status bar
// item that on this computer leaves the place to the SDK setup status.
//
// sima-cli, curl and the installer are fake scripts; HOME is a temporary folder.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { ROOT, tempDir, requireWithVscode } = require('./helpers');
const { createFakeVscode, fakeContext, settle } = require('./fakeVscode');
const { stubHttpsGet } = require('./fakeHttp');

const STUBBED = {
  'setupPanel.js': null, // replaced below to catch the API the extension gives the page
  'hostStatus.js': { register() {} },
  'container.js': { init() {} },
  'devcontainer.js': { init() {}, openOnStartup() {}, openSdkInVsCode() {}, isDevContainersInstalled: () => false },
  neat: { register: () => ({ openInsight() {} }) },
  agents: { init: async () => {}, connectContainerClaude() {} },
  'sdkWindow.js': { arrange() {} },
};

function writeScript(file, body) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `#!/bin/sh\n${body}\n`, { mode: 0o755 });
}

/** A JWT with these claims (not signed; the extension only reads it). */
function idToken(claims) {
  const part = (value) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${part({ alg: 'none' })}.${part(claims)}.sig`;
}

/**
 * Activates extension.js with HOME and PATH in temporary folders, and returns
 * the API it hands to the Set up SDK page.
 */
async function activate(t, { simaCli, curl, remoteName } = {}) {
  const home = tempDir(t);
  const bin = path.join(home, 'bin');
  fs.mkdirSync(bin);
  const saved = { HOME: process.env.HOME, PATH: process.env.PATH };
  process.env.HOME = home;
  process.env.PATH = `${bin}${path.delimiter}/usr/bin${path.delimiter}/bin`;
  t.after(() => Object.assign(process.env, saved));

  if (simaCli) {
    writeScript(path.join(bin, 'sima-cli'), simaCli);
  }
  if (curl) {
    writeScript(path.join(bin, 'curl'), curl);
  }

  for (const key of Object.keys(require.cache)) {
    if (key.startsWith(ROOT) && !key.includes(`${path.sep}test${path.sep}`) && !key.includes('node_modules')) {
      delete require.cache[key];
    }
  }
  let api;
  const stubs = { ...STUBBED, 'setupPanel.js': { init: (_context, given) => { api = given; }, show() {}, dispose() {} } };
  for (const [name, exports] of Object.entries(stubs)) {
    const file = require.resolve(path.join(ROOT, name));
    require.cache[file] = { id: file, filename: file, loaded: true, exports };
  }

  const fake = createFakeVscode({ remoteName });
  const extension = requireWithVscode(path.join(ROOT, 'extension.js'), fake.vscode);
  const context = fakeContext(ROOT);
  await context.globalState.update('simaNeat.setupShown', true);
  await extension.activate(context);
  return { api, fake, home, bin, context };
}

/** sima-cli that answers --version and runs `login` as given. */
const simaCliWith = (login) => `
if [ "$1" = "--version" ]; then echo "sima-cli version: 0.0.40"; exit 0; fi
if [ "$1" = "login" ]; then
${login}
fi
exit 0`;

const tokensFile = (home) => path.join(home, '.sima-cli', '.tokens.json');

function writeTokens(home, claims) {
  fs.mkdirSync(path.dirname(tokensFile(home)), { recursive: true });
  fs.writeFileSync(tokensFile(home), JSON.stringify({ refresh_token: 'r', id_token: idToken(claims) }));
}

test('readLoginState: name and email from the id token', async (t) => {
  const { api, home } = await activate(t, { simaCli: simaCliWith('exit 0') });
  assert.deepEqual(api.readLoginState().external, { loggedIn: false });

  writeTokens(home, { email: 'ana@sima.ai', name: 'Ana Dev' });
  assert.deepEqual(api.readLoginState().external, { loggedIn: true, user: 'ana@sima.ai', name: 'Ana Dev', email: 'ana@sima.ai' });
});

test('readLoginState: the email from the SiMa user_info claim; a name equal to the email is dropped', async (t) => {
  const { api, home } = await activate(t, { simaCli: simaCliWith('exit 0') });
  writeTokens(home, { name: 'ana@sima.ai', 'https://auth.sima.ai/user_info': { email: 'ana@sima.ai' } });
  assert.deepEqual(api.readLoginState().external, { loggedIn: true, user: 'ana@sima.ai', name: '', email: 'ana@sima.ai' });

  writeTokens(home, { nickname: 'ana' });
  assert.deepEqual(api.readLoginState().external, { loggedIn: true, user: 'ana', name: '', email: undefined });
});

test('loginQuietly: signs in through sima-cli without a terminal', async (t) => {
  const { api, home } = await activate(t, {
    simaCli: simaCliWith(`
mkdir -p "$HOME/.sima-cli"
echo '{"refresh_token":"r"}' > "$HOME/.sima-cli/.tokens.json"
echo "SIMA_CLI_CHECK_FOR_UPDATE=$SIMA_CLI_CHECK_FOR_UPDATE"
exit 0`),
  });
  const run = api.loginQuietly();
  assert.equal(typeof run.cancel, 'function');
  assert.deepEqual(await run.done, { ok: true });
  assert.ok(fs.existsSync(tokensFile(home)));
});

test('loginQuietly: the reason is the last line of the output, without colours, emoji and rules', async (t) => {
  const { api } = await activate(t, {
    simaCli: simaCliWith(`
printf '\\033[1;34m🔐 Opening the browser…\\033[0m\\n'
echo "════════════"
printf '\\033[31m❌ Login timed out after 300 seconds\\033[0m\\n'
echo "------------"
echo "   "
exit 1`),
  });
  assert.deepEqual(await api.loginQuietly().done, { ok: false, cancelled: false, reason: 'Login timed out after 300 seconds' });
});

test('loginQuietly: no output gives the exit code; exit 0 without tokens is not a sign-in', async (t) => {
  const failing = await activate(t, { simaCli: simaCliWith('exit 4') });
  assert.deepEqual(await failing.api.loginQuietly().done, { ok: false, cancelled: false, reason: 'sima-cli login stopped (exit 4).' });

  const noTokens = await activate(t, { simaCli: simaCliWith('echo "Done"; exit 0') });
  assert.deepEqual(await noTokens.api.loginQuietly().done, { ok: false, cancelled: false, reason: 'Done' });
});

test('loginQuietly: Cancel stops sima-cli and what it started', async (t) => {
  const { api, home } = await activate(t, {
    simaCli: simaCliWith(`
sleep 30 &
echo $! > "$HOME/child.pid"
echo "Waiting for the browser…"
wait`),
  });
  const run = api.loginQuietly();
  const pidFile = path.join(home, 'child.pid');
  for (let i = 0; i < 50 && !fs.existsSync(pidFile); i += 1) {
    await settle(20);
  }
  const childPid = Number(fs.readFileSync(pidFile, 'utf8'));
  run.cancel();
  const result = await run.done;
  assert.equal(result.ok, false);
  assert.equal(result.cancelled, true);
  await settle(100);
  assert.throws(() => process.kill(childPid, 0), { code: 'ESRCH' }, 'the browser opener / helper is stopped too');
});

test('loginQuietly: finishes when sima-cli exits even if something it started keeps the output open', async (t) => {
  const { api, home } = await activate(t, {
    simaCli: simaCliWith(`
mkdir -p "$HOME/.sima-cli"
echo '{"refresh_token":"r"}' > "$HOME/.sima-cli/.tokens.json"
sleep 5 &
echo $! > "$HOME/child.pid"
exit 0`),
  });
  const started = Date.now();
  assert.deepEqual(await api.loginQuietly().done, { ok: true });
  assert.ok(Date.now() - started < 3000, 'did not wait for the background process');
  try {
    process.kill(Number(fs.readFileSync(path.join(home, 'child.pid'), 'utf8')), 'SIGKILL');
  } catch {
    // already gone
  }
});

/** curl that serves an installer script with this body. */
const curlServing = (installer) => `
for arg in "$@"; do last="$arg"; done
echo "$last" > "$HOME/installer-url"
cat <<'INSTALLER'
${installer}
INSTALLER`;

test('installSimaCliQuietly: runs the official installer and finds the new sima-cli', async (t) => {
  const { api, home } = await activate(t, {
    curl: curlServing(`
echo "DEBIAN_FRONTEND=$DEBIAN_FRONTEND SUDO_ASKPASS=$SUDO_ASKPASS" > "$HOME/installer-env"
mkdir -p "$HOME/.sima-cli/.venv/bin"
printf '#!/bin/sh\\necho "sima-cli version: 0.0.41"\\n' > "$HOME/.sima-cli/.venv/bin/sima-cli"
chmod +x "$HOME/.sima-cli/.venv/bin/sima-cli"
echo "Installed"`),
  });
  assert.equal(api.getSimaCli(), undefined);
  assert.deepEqual(await api.installSimaCliQuietly().done, { ok: true });
  assert.equal(fs.readFileSync(path.join(home, 'installer-url'), 'utf8').trim(), 'https://artifacts.neat.sima.ai/sima-cli/linux-mac.sh');
  assert.equal(fs.readFileSync(path.join(home, 'installer-env'), 'utf8').trim(), 'DEBIAN_FRONTEND=noninteractive SUDO_ASKPASS=/bin/false');
  const cli = api.getSimaCli();
  assert.equal(cli.file, path.join(home, '.sima-cli', '.venv', 'bin', 'sima-cli'));
  assert.equal(cli.version, '0.0.41');
});

test('installSimaCliQuietly: an installer that needs sudo asks for the terminal install', async (t) => {
  const { api } = await activate(t, {
    curl: curlServing('echo "sudo: a terminal is required to read the password"; exit 1'),
  });
  assert.deepEqual(await api.installSimaCliQuietly().done, {
    ok: false,
    cancelled: false,
    needsTerminal: true,
    reason: 'Installing the SiMa command-line tools needs your password. Install them in a terminal, then try again.',
  });
});

test('installSimaCliQuietly: other failures show the installer\'s last line or its exit code', async (t) => {
  const python = await activate(t, {
    curl: curlServing(`printf '\\033[31m❌ Python 3.10 or later was not found\\033[0m\\n'; exit 2`),
  });
  assert.deepEqual(await python.api.installSimaCliQuietly().done, {
    ok: false, cancelled: false, needsTerminal: false, reason: 'Python 3.10 or later was not found',
  });

  const silent = await activate(t, { curl: curlServing('exit 3') });
  assert.deepEqual(await silent.api.installSimaCliQuietly().done, {
    ok: false, cancelled: false, needsTerminal: false, reason: 'The sima-cli installer stopped (exit 3).',
  });
});

test('installSimaCliQuietly: a download that fails stops the install (pipefail)', async (t) => {
  const { api } = await activate(t, { curl: 'echo "curl: (6) Could not resolve host" >&2; exit 6' });
  const result = await api.installSimaCliQuietly().done;
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'curl: (6) Could not resolve host');
});

test('installSimaCliQuietly: Cancel stops the installer', async (t) => {
  const { api } = await activate(t, { curl: curlServing('sleep 30') });
  const run = api.installSimaCliQuietly();
  await settle(200);
  run.cancel();
  const result = await run.done;
  assert.equal(result.ok, false);
  assert.equal(result.cancelled, true);
});

test('latestSimaCliVersion reads PyPI and is empty when it cannot', async (t) => {
  const { api } = await activate(t, { simaCli: simaCliWith('exit 0') });

  let answer = { body: { info: { version: '0.0.41' } } };
  const requests = stubHttpsGet(t, () => answer);
  assert.equal(await api.latestSimaCliVersion(), '0.0.41');
  assert.equal(requests[0].url, 'https://pypi.org/pypi/sima-cli/json');
  assert.equal(requests[0].headers['User-Agent'], 'sima-neat-desktop');

  answer = { status: 503, body: 'down' };
  assert.equal(await api.latestSimaCliVersion(), '');
  answer = { body: 'not json' };
  assert.equal(await api.latestSimaCliVersion(), '');
  answer = 'timeout';
  assert.equal(await api.latestSimaCliVersion(), '');
});

test('latestSimaCliVersion is empty without a network', async (t) => {
  const { api } = await activate(t, { simaCli: simaCliWith('exit 0') });
  stubHttpsGet(t, () => { throw new Error('ENOTFOUND pypi.org'); });
  assert.equal(await api.latestSimaCliVersion(), '');
});

test('on this computer the sima-cli status bar item stays hidden', async (t) => {
  const { fake } = await activate(t, { simaCli: simaCliWith('exit 0') });
  const item = fake.statusItems.find((i) => i.priority === 100);
  assert.ok(item);
  assert.equal(item.visible, false);
});

test('inside the SDK container the sima-cli status bar item still shows', async (t) => {
  const { fake } = await activate(t, { remoteName: 'attached-container' });
  const item = fake.statusItems.find((i) => i.priority === 100);
  assert.equal(item.visible, true);
  assert.equal(item.text, '$(cloud-download) Install sima-cli');
});
