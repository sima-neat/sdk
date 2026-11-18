'use strict';

// The Set up SDK page itself (media/setup.html + media/setup.js) in jsdom: the step list
// with its summaries, "Step N of 5" and the heading, the Sign in card in each phase,
// Continue, staying on a step after pressing one of its buttons, hover tips of
// "Check this computer", one primary button per step, and what it tells the extension.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const { ROOT } = require('./helpers');

const HTML = fs.readFileSync(path.join(ROOT, 'media', 'setup.html'), 'utf8')
  .replace(/\{\{\w+\}\}/g, '')
  .replace(/<script[^>]*><\/script>/, '');
const SCRIPT = fs.readFileSync(path.join(ROOT, 'media', 'setup.js'), 'utf8');

const CHECKS_OK = [
  { id: 'os', label: 'Host OS', group: 'required', status: 'ok', detail: 'Ubuntu 24.04.5 LTS · x86_64' },
  { id: 'docker', label: 'Docker', group: 'required', status: 'ok', detail: 'Docker Engine 29.9.3' },
  { id: 'daemon', label: 'Docker daemon', group: 'required', status: 'ok', detail: 'Running' },
  { id: 'disk', label: 'Disk space', group: 'required', status: 'ok', detail: '180 GB free · needs ~20 GB' },
  { id: 'ethtool', label: 'ethtool', group: 'optional', status: 'ok', detail: 'Installed' },
];

/** CHECKS_OK with some items replaced, by id. */
const checks = (changes) => CHECKS_OK.map((i) => (changes[i.id] ? { ...i, ...changes[i.id] } : i));

const DOCKER_MISSING = {
  docker: {
    status: 'error',
    detail: 'Not installed',
    fix: {
      text: 'Docker runs the SDK container on this computer. Install Docker Desktop, start it once, then Check again.',
      link: { label: 'Install Docker Desktop', url: 'https://docs.docker.com/desktop/' },
    },
  },
  daemon: { status: 'skip', detail: 'Checked after Docker is installed' },
};
const ETHTOOL_MISSING = {
  ethtool: {
    status: 'warn',
    detail: 'Missing',
    fix: {
      text: 'ethtool is optional. Without it, Neat Studio can’t find DevKits on your network automatically — you can still enter the DevKit IP yourself in Configure.',
      link: { label: 'How to install ethtool', url: 'https://packages.ubuntu.com/search?keywords=ethtool' },
    },
  },
};

/** The state the extension sends, as SetupPanel builds it; `over` replaces parts of it. */
function baseState(over = {}) {
  return {
    cli: { found: true, version: '0.0.41', file: '/home/me/.sima-cli/.venv/bin/sima-cli' },
    login: { loggedIn: false },
    signin: { phase: 'idle' },
    cliLatest: '0.0.41',
    prereqs: { status: 'ok', items: CHECKS_OK },
    versions: { status: 'ok', items: [{ ref: 'v3.0.0.1', label: 'v3.0.0.1', recommended: true }] },
    selectedRef: 'v3.0.0.1',
    release: { status: 'ok', ref: 'v3.0.0.1', version: '3.0.0.1', image: 'ghcr.io/sima-neat/sdk:v3.0.0.1', resource: 'ghcr:sima-neat/sdk:v3.0.0.1', requiredGb: 20 },
    image: { status: 'missing' },
    containers: [],
    pull: { state: 'idle' },
    config: { devkitMode: 'none', devkitIp: '', modelCompiler: 'skip', codingAgents: 'skip', edgematicStudio: false, workspace: '~/workspace' },
    configErrors: {},
    command: 'sima-cli sdk setup',
    setup: { state: 'idle' },
    ideAvailable: false,
    devContainers: true,
    reset: { status: 'closed' },
    ...over,
  };
}

const SIGNED_IN = { login: { loggedIn: true, user: 'ana@sima.ai', name: 'Ana Dev', email: 'ana@sima.ai' } };

const openWindows = [];
test.afterEach(() => {
  while (openWindows.length) {
    openWindows.pop().close();
  }
});

/**
 * Opens the page in jsdom; `saved` is what vscode.getState() returns (the page's memory).
 * By default the user has already continued past Check this computer.
 */
function openPage(saved = { checkConfirmed: true }) {
  const dom = new JSDOM(HTML, { runScripts: 'outside-only' });
  const { window } = dom;
  openWindows.push(window);
  const posted = [];
  const memory = { value: saved };
  // Copies made here, as a real webview passes plain data (and jsdom objects are from another realm).
  const copy = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
  window.acquireVsCodeApi = () => ({
    postMessage: (message) => posted.push(copy(message)),
    getState: () => memory.value,
    setState: (value) => { memory.value = copy(value); },
  });
  window.eval(SCRIPT);
  const doc = window.document;
  const $ = (id) => doc.getElementById(id);
  const page = {
    window, doc, $, posted, memory,
    send(state) {
      window.dispatchEvent(new window.MessageEvent('message', { data: { type: 'state', state } }));
    },
    click(el) {
      el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
    },
    /** Hidden itself or inside something hidden. */
    shown: (el) => Boolean(el) && !el.closest('[hidden]'),
    stepCount: () => $('step-count').textContent,
    title: () => $('heading-title').textContent,
    lead: () => $('heading-lead').textContent,
    openPane: () => doc.querySelector('[data-pane]:not([hidden])').dataset.pane,
    rail: () => [...doc.querySelectorAll('#rail-items .rail-item')].map((item) => ({
      name: item.querySelector('.rail-name').textContent,
      dot: item.querySelector('.rail-dot').className.replace('rail-dot', '').trim(),
      mark: item.querySelector('.rail-dot').textContent || (item.querySelector('.rail-dot i') || {}).className,
      summary: (item.querySelector('.rail-summary') || {}).textContent,
      bar: item.querySelector('.rail-bar > div') ? item.querySelector('.rail-bar > div').style.width : undefined,
      viewing: item.classList.contains('viewing'),
      clickable: item.classList.contains('clickable'),
    })),
    /** The check rows: [label, icon, value, value class]. */
    checkRows: () => [...doc.querySelectorAll('#prereq-groups .ck-row')].map((row) => [
      row.querySelector('.ck-label').textContent,
      row.querySelector('.ck-mark i').className,
      row.querySelector('.ck-value').textContent,
      row.querySelector('.ck-value').className,
    ]),
    checkGroups: () => [...doc.querySelectorAll('#prereq-groups .ck-group')].map((g) => [
      g.querySelector('.ck-group-title').textContent,
      g.querySelector('.ck-group-sub').textContent,
      g.querySelectorAll('.ck-row').length,
    ]),
    railItem: (name) => [...doc.querySelectorAll('#rail-items .rail-item')].find((i) => i.querySelector('.rail-name').textContent === name),
    actions: () => posted.filter((m) => m.type === 'action'),
    hostStatus: () => posted.filter((m) => m.type === 'hostStatus').at(-1),
    /** Visible buttons of the open pane plus Continue, and whether each is primary. */
    primaryButtons() {
      const pane = doc.querySelector('[data-pane]:not([hidden])');
      return [...pane.querySelectorAll('button'), $('continue-button')]
        .filter((b) => page.shown(b) && !b.classList.contains('secondary') && !b.classList.contains('link') && !b.classList.contains('danger'))
        .map((b) => b.textContent.trim());
    },
  };
  return page;
}

test('asks the extension for its state once loaded', () => {
  const page = openPage();
  assert.deepEqual(page.posted, [{ type: 'ready' }]);
});

test('step 1: Sign in to SiMa, with five steps in the list', () => {
  const page = openPage();
  page.send(baseState());
  assert.equal(page.stepCount(), 'Step 1 of 5');
  assert.equal(page.title(), 'Sign in to SiMa');
  assert.equal(page.lead(), 'One browser sign-in to the SiMa Developer Portal. It covers the SDK download, the Model Registry and Insight. The SiMa command-line tools are installed for you.');
  assert.equal(page.openPane(), 'signin');
  assert.deepEqual(page.rail().map((r) => [r.name, r.mark, r.dot, r.viewing]), [
    ['Sign in', '1', 'active', true],
    ['Check this computer', '2', '', false],
    ['Download SDK', '3', '', false],
    ['Configure', '4', '', false],
    ['Start Neat Studio', '5', '', false],
  ]);
  assert.ok(page.shown(page.$('si-signin')));
  for (const id of ['si-done', 'si-pending', 'si-error', 'si-cancel', 'si-retry', 'si-terminal', 'si-continue', 'si-signout']) {
    assert.equal(page.shown(page.$(id)), false, `${id} is hidden`);
  }
  assert.equal(page.shown(page.$('continue-button')), false, 'Sign in has its own buttons');
  assert.equal(page.shown(page.$('reset')), false, 'Start over is only on the last step');
  assert.deepEqual(page.hostStatus(), { type: 'hostStatus', value: { active: 1, total: 5 } });
});

test('Sign in: pressing the button asks the extension to sign in', () => {
  const page = openPage();
  page.send(baseState());
  page.click(page.$('si-signin'));
  assert.deepEqual(page.actions().at(-1), { type: 'action', id: 'signin' });
});

test('Sign in: installing sima-cli, then waiting for the browser, with Cancel', () => {
  const page = openPage();
  page.send(baseState({ cli: { found: false }, signin: { phase: 'installing' } }));
  assert.ok(page.shown(page.$('si-pending')));
  assert.equal(page.$('si-pending-text').textContent, 'Installing the SiMa command-line tools…');
  assert.ok(page.shown(page.$('si-signin')));
  assert.equal(page.$('si-signin').disabled, true);
  assert.ok(page.shown(page.$('si-cancel')));

  page.send(baseState({ signin: { phase: 'pending' } }));
  assert.equal(page.$('si-pending-text').textContent, 'Finish signing in in your browser…');
  page.click(page.$('si-cancel'));
  assert.equal(page.actions().at(-1).id, 'signinCancel');

  // A disabled button sends nothing.
  const before = page.actions().length;
  page.click(page.$('si-signin'));
  assert.equal(page.actions().length, before);
});

test('Sign in: a failure shows the reason and Try again; the terminal only when a password is needed', () => {
  const page = openPage();
  page.send(baseState({ signin: { phase: 'error', reason: 'Login timed out.' } }));
  assert.ok(page.shown(page.$('si-error')));
  assert.equal(page.$('si-error-reason').textContent, 'Reason: Login timed out.');
  assert.ok(page.shown(page.$('si-retry')));
  assert.equal(page.shown(page.$('si-terminal')), false);
  assert.equal(page.shown(page.$('si-signin')), false);

  page.send(baseState({ cli: { found: false }, signin: { phase: 'error', needsTerminal: true } }));
  assert.equal(page.$('si-error-reason').textContent, 'Reason: Sign-in did not finish.');
  assert.ok(page.shown(page.$('si-terminal')));
  page.click(page.$('si-terminal'));
  assert.equal(page.actions().at(-1).id, 'installCli');
  page.click(page.$('si-retry'));
  assert.equal(page.actions().at(-1).id, 'signin');
});

test('Sign in: signed in shows who, sima-cli details, Continue and Sign out', () => {
  const page = openPage();
  page.send(baseState({ ...SIGNED_IN, cliLatest: '0.0.42' }));
  page.click(page.railItem('Sign in'));
  assert.ok(page.shown(page.$('si-done')));
  assert.equal(page.$('si-who').textContent, 'Signed in as Ana Dev · ana@sima.ai');
  assert.equal(page.$('si-who').querySelector('b').textContent, 'Ana Dev');
  assert.ok(page.shown(page.$('si-continue')));
  assert.ok(page.shown(page.$('si-signout')));
  assert.equal(page.shown(page.$('si-signin')), false);

  assert.equal(page.shown(page.$('si-details')), false, 'details are hidden by default');
  assert.equal(page.$('si-details-toggle').textContent, 'Show details');
  page.click(page.$('si-details-toggle'));
  assert.ok(page.shown(page.$('si-details')));
  assert.equal(page.$('si-details-toggle').textContent, 'Hide details');
  assert.equal(page.$('si-cli').textContent, '0.0.41 · update available (0.0.42)');
  page.click(page.$('si-details-toggle'));
  assert.equal(page.shown(page.$('si-details')), false);

  page.click(page.$('si-signout'));
  assert.equal(page.actions().at(-1).id, 'logout');
});

test('Sign in: who and sima-cli version for each kind of account and version', () => {
  const page = openPage();
  page.send(baseState({ login: { loggedIn: true, user: 'ana@sima.ai', email: 'ana@sima.ai' } }));
  assert.equal(page.$('si-who').textContent, 'Signed in as ana@sima.ai');
  assert.equal(page.$('si-cli').textContent, '0.0.41 · installed and up to date');

  page.send(baseState({ login: { loggedIn: true }, cliLatest: '' }));
  assert.equal(page.$('si-who').textContent, 'Signed in as you');
  assert.equal(page.$('si-cli').textContent, '0.0.41 · installed');

  page.send(baseState({ login: { loggedIn: true }, cli: { found: true }, cliLatest: '0.0.41' }));
  assert.equal(page.$('si-cli').textContent, 'unknown version · installed and up to date');

  page.send(baseState({ cli: { found: false } }));
  assert.equal(page.$('si-cli').textContent, 'not installed');
});

test('Continue on Sign in opens Check this computer', () => {
  const page = openPage({});
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'checking', items: [] } }));
  assert.equal(page.stepCount(), 'Step 2 of 5', 'once signed in, the page moves on by itself');
  page.click(page.railItem('Sign in'));
  assert.equal(page.stepCount(), 'Step 1 of 5');
  page.click(page.$('si-continue'));
  assert.equal(page.stepCount(), 'Step 2 of 5');
  assert.equal(page.title(), 'Check this computer');
  assert.equal(page.lead(), 'Checking what the SDK needs…');
  assert.equal(page.openPane(), 'check');
  assert.deepEqual(page.memory.value, { viewing: 'check', configConfirmed: false, checkConfirmed: false });
});

test('Check this computer · all OK (A2a): Required and Optional lists, Continue, no Check again', () => {
  const page = openPage({});
  page.send(baseState(SIGNED_IN));
  assert.equal(page.stepCount(), 'Step 2 of 5', 'stays on the step until the user continues');
  assert.equal(page.title(), 'Check this computer');
  assert.equal(page.lead(), 'Everything the SDK needs is here. Hover a status icon to see why each item matters.');
  assert.deepEqual(page.rail()[1], {
    name: 'Check this computer', dot: 'active', mark: '2', summary: undefined, bar: undefined, viewing: true, clickable: false,
  });
  assert.deepEqual(page.checkGroups(), [
    ['Required', 'Setup can’t continue without these', 4],
    ['Optional', 'Setup continues without it', 1],
  ]);
  assert.deepEqual(page.checkRows(), [
    ['Host OS', 'codicon codicon-pass', 'Ubuntu 24.04.5 LTS · x86_64', 'ck-value'],
    ['Docker', 'codicon codicon-pass', 'Docker Engine 29.9.3', 'ck-value'],
    ['Docker daemon', 'codicon codicon-pass', 'Running', 'ck-value'],
    ['Disk space', 'codicon codicon-pass', '180 GB free · needs ~20 GB', 'ck-value'],
    ['ethtool', 'codicon codicon-pass', 'Installed', 'ck-value'],
  ]);
  const tips = [...page.doc.querySelectorAll('#prereq-groups .ck-mark')].map((m) => m.title);
  assert.deepEqual(tips, [
    'Supported: Ubuntu 22.04+, macOS 14+ (Apple silicon), Windows 11 with WSL 2.',
    'The SDK runs as a Docker container. Needs Docker 24 or later.',
    'Docker must be running to download and start the SDK.',
    'The SDK image and its data need about 20 GB.',
    'Used to find DevKits on your network automatically. Without it you can still enter the DevKit IP yourself.',
  ]);
  assert.equal(page.shown(page.$('prereq-fix')), false);
  assert.ok(page.shown(page.$('continue-button')));
  assert.equal(page.$('continue-button').disabled, false);
  assert.equal(page.shown(page.$('prereq-recheck')), false, 'no Check again when everything passed');
  assert.equal(page.shown(page.$('nav-reason')), false);
  assert.deepEqual(page.hostStatus().value, { active: 2, total: 5 });

  page.click(page.$('continue-button'));
  assert.equal(page.title(), 'Download the SDK');
  assert.equal(page.rail()[1].summary, 'All required checks passed');
  assert.equal(page.memory.value.checkConfirmed, true);
});

test('Check · Docker not installed (A2b): the fix with its link, Continue disabled, Check again, lock line', () => {
  const page = openPage({});
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'error', items: checks(DOCKER_MISSING) } }));
  assert.equal(page.lead(), 'A required item needs your attention before setup can continue.');
  assert.deepEqual(page.checkRows().slice(1, 3), [
    ['Docker', 'codicon codicon-error', 'Not installed', 'ck-value error'],
    ['Docker daemon', 'codicon codicon-circle-large-outline', 'Checked after Docker is installed', 'ck-value'],
  ]);
  assert.ok(page.shown(page.$('prereq-fix')));
  assert.equal(page.$('prereq-fix-icon').className, 'codicon codicon-error');
  assert.equal(page.$('prereq-fix-text').textContent, 'Docker runs the SDK container on this computer. Install Docker Desktop, start it once, then Check again.');
  assert.ok(page.shown(page.$('prereq-fix-link')));
  assert.equal(page.$('prereq-fix-link-label').textContent, 'Install Docker Desktop');
  page.click(page.$('prereq-fix-link'));
  assert.deepEqual(page.actions().at(-1), { type: 'action', id: 'openLink', value: 'https://docs.docker.com/desktop/' });

  assert.ok(page.shown(page.$('continue-button')), 'Continue is shown, as in the design');
  assert.equal(page.$('continue-button').disabled, true);
  assert.ok(page.shown(page.$('prereq-recheck')));
  assert.equal(page.$('prereq-recheck').classList.contains('secondary'), true);
  assert.ok(page.shown(page.$('nav-reason')));
  assert.equal(page.$('nav-reason').textContent, 'Fix the required item above, then Check again.');
  assert.deepEqual(page.primaryButtons(), ['Continue']);
  const order = [...page.$('nav-buttons').querySelectorAll('button')].filter(page.shown).map((b) => b.textContent);
  assert.deepEqual(order, ['Continue', 'Check again']);
});

test('Check · Docker daemon not running (A2c): the fix shows its command as code, no link', () => {
  const page = openPage({});
  page.send(baseState({
    ...SIGNED_IN,
    prereqs: {
      status: 'error',
      items: checks({ daemon: { status: 'error', detail: 'Not running', fix: { text: 'Docker is installed but not running. Start it with `sudo systemctl start docker`, then Check again.' } } }),
    },
  }));
  assert.deepEqual(page.checkRows()[2], ['Docker daemon', 'codicon codicon-error', 'Not running', 'ck-value error']);
  assert.equal(page.$('prereq-fix-text').textContent, 'Docker is installed but not running. Start it with sudo systemctl start docker, then Check again.');
  assert.equal(page.$('prereq-fix-text').querySelector('code').textContent, 'sudo systemctl start docker');
  assert.equal(page.shown(page.$('prereq-fix-link')), false);
});

test('Check · not enough disk space (A2d)', () => {
  const page = openPage({});
  page.send(baseState({
    ...SIGNED_IN,
    prereqs: { status: 'error', items: checks({ disk: { status: 'error', detail: '14 GB free · needs ~20 GB', fix: { text: 'Free up about 6 GB, then Check again.' } } }) },
  }));
  assert.deepEqual(page.checkRows()[3], ['Disk space', 'codicon codicon-error', '14 GB free · needs ~20 GB', 'ck-value error']);
  assert.equal(page.$('prereq-fix-text').textContent, 'Free up about 6 GB, then Check again.');
  assert.equal(page.$('continue-button').disabled, true);
});

test('Check · ethtool missing (A2e): a warning, Continue still works, no lock line', () => {
  const page = openPage({});
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'warn', items: checks(ETHTOOL_MISSING) } }));
  assert.equal(page.title(), 'Check this computer');
  assert.equal(page.lead(), 'Ready to continue. One optional item is missing.');
  assert.deepEqual(page.checkRows()[4], ['ethtool', 'codicon codicon-warning', 'Missing', 'ck-value warn']);
  assert.equal(page.$('prereq-fix-icon').className, 'codicon codicon-warning');
  assert.equal(page.$('prereq-fix-link-label').textContent, 'How to install ethtool');
  page.click(page.$('prereq-fix-link'));
  assert.deepEqual(page.actions().at(-1), { type: 'action', id: 'openLink', value: 'https://packages.ubuntu.com/search?keywords=ethtool' });
  assert.equal(page.$('continue-button').disabled, false);
  assert.ok(page.shown(page.$('prereq-recheck')));
  assert.equal(page.shown(page.$('nav-reason')), false);

  page.click(page.$('continue-button'));
  assert.equal(page.title(), 'Download the SDK');
  assert.equal(page.rail()[1].summary, 'Ready · ethtool missing (optional)');
});

test('Check · checking: every row spins the first time; later the host and Docker keep their result', () => {
  const page = openPage({});
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'checking', items: [] } }));
  assert.equal(page.lead(), 'Checking what the SDK needs…');
  assert.deepEqual(page.checkRows().map((r) => [r[0], r[1], r[2]]), [
    ['Host OS', 'codicon codicon-loading codicon-modifier-spin', 'Checking…'],
    ['Docker', 'codicon codicon-loading codicon-modifier-spin', 'Checking…'],
    ['Docker daemon', 'codicon codicon-loading codicon-modifier-spin', 'Checking…'],
    ['Disk space', 'codicon codicon-loading codicon-modifier-spin', 'Checking…'],
    ['ethtool', 'codicon codicon-loading codicon-modifier-spin', 'Checking…'],
  ]);
  assert.equal(page.$('continue-button').disabled, true);
  assert.equal(page.shown(page.$('prereq-recheck')), false);
  assert.equal(page.shown(page.$('prereq-fix')), false);
  assert.equal(page.shown(page.$('nav-reason')), false);

  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'checking', items: checks(DOCKER_MISSING) } }));
  assert.deepEqual(page.checkRows().map((r) => r[2]), ['Ubuntu 24.04.5 LTS · x86_64', 'Not installed', 'Checking…', 'Checking…', 'Checking…']);
  assert.equal(page.shown(page.$('prereq-fix')), false, 'no fix while checking again');
});

test('Check · several problems: all are marked, the fix is for the first one', () => {
  const page = openPage({});
  const items = checks({
    ...ETHTOOL_MISSING,
    disk: { status: 'error', detail: '3 GB free · needs ~20 GB', fix: { text: 'Free up about 17 GB, then Check again.' } },
    daemon: { status: 'error', detail: 'Not running', fix: { text: 'Start Docker.' } },
  });
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'error', items } }));
  assert.deepEqual(page.checkRows().map((r) => r[3]), ['ck-value', 'ck-value', 'ck-value error', 'ck-value error', 'ck-value warn']);
  assert.equal(page.$('prereq-fix-text').textContent, 'Start Docker.');
});

test('Check · a required warning (unsupported OS) still lets setup continue', () => {
  const page = openPage({});
  const items = checks({ os: { status: 'warn', detail: 'Fedora Linux 40 · x86_64', fix: { text: 'The SDK is tested on Ubuntu 22.04 and 24.04. Other hosts may work.' } } });
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'warn', items } }));
  assert.equal(page.lead(), 'Ready to continue. One item needs your attention.');
  assert.equal(page.$('prereq-fix-text').textContent, 'The SDK is tested on Ubuntu 22.04 and 24.04. Other hosts may work.');
  assert.equal(page.shown(page.$('prereq-fix-link')), false);
  page.click(page.$('continue-button'));
  assert.equal(page.rail()[1].summary, 'Ready · Host OS: Fedora Linux 40 · x86_64');
});

test('Check this computer opened again from the step list: Continue goes back on', () => {
  const page = openPage();
  page.send(baseState(SIGNED_IN));
  assert.equal(page.title(), 'Download the SDK');
  page.click(page.railItem('Check this computer'));
  assert.equal(page.title(), 'Check this computer');
  assert.ok(page.shown(page.$('continue-button')));
  page.click(page.$('continue-button'));
  assert.equal(page.title(), 'Download the SDK');
});

test('the page follows the current step: signed in and checked opens Download SDK', () => {
  const page = openPage();
  page.send(baseState(SIGNED_IN));
  assert.equal(page.stepCount(), 'Step 3 of 5');
  assert.equal(page.title(), 'Download the SDK');
  assert.equal(page.lead(), 'The SDK is a Docker image with the toolchain, Neat and examples. Configure opens as soon as the download starts.');
  assert.deepEqual(page.rail().map((r) => [r.mark, r.summary]), [
    ['codicon codicon-check', 'Signed in as Ana Dev'],
    ['codicon codicon-check', 'All required checks passed'],
    ['3', undefined],
    ['4', undefined],
    ['5', undefined],
  ]);
  assert.deepEqual(page.hostStatus().value, { active: 3, total: 5 });
});

test('Download SDK: while downloading, the list shows version, percentage and GB, and Configure opens', () => {
  const page = openPage();
  page.send(baseState({
    ...SIGNED_IN,
    pull: { state: 'running', progress: { done: 3, total: 9, bytesDone: 4_242_000_000, bytesTotal: 10_100_000_000 } },
  }));
  assert.equal(page.stepCount(), 'Step 4 of 5', 'a running download counts as passed');
  assert.equal(page.title(), 'Configure the SDK');
  assert.equal(page.lead(), 'Choose what goes into your SDK. You can change any of this later.');
  const download = page.rail()[2];
  assert.equal(download.mark, 'codicon codicon-loading codicon-modifier-spin');
  assert.equal(download.dot, 'busy');
  assert.equal(download.summary, 'v3.0.0.1 · 42% · 4.2 of 10.1 GB');
  assert.equal(download.bar, '42%');
  assert.equal(download.clickable, true);
  assert.equal(page.rail()[3].summary, undefined, 'Configure has no summary until it is done');

  // Opened from the list: Continue moves on while the download runs.
  page.click(page.railItem('Download SDK'));
  assert.equal(page.lead(), 'Downloading in the background. Setup keeps going while you wait.');
  assert.ok(page.shown(page.$('continue-button')));
  page.click(page.$('continue-button'));
  assert.equal(page.title(), 'Configure the SDK');
});

test('Download SDK: before the layer sizes are known, the percentage counts layers and GB is left out', () => {
  const page = openPage();
  page.send(baseState({ ...SIGNED_IN, pull: { state: 'waiting', progress: { done: 1, total: 4 } } }));
  assert.equal(page.rail()[2].summary, 'v3.0.0.1 · 25%');
});

test('Download SDK: a failed download stays on the step with a warning in the list', () => {
  const page = openPage();
  page.send(baseState({
    ...SIGNED_IN,
    pull: { state: 'failed', error: { message: 'net', hint: '' }, progress: { done: 0, total: 0, bytesDone: 1_717_000_000, bytesTotal: 10_100_000_000 } },
  }));
  assert.equal(page.stepCount(), 'Step 3 of 5');
  const download = page.rail()[2];
  assert.equal(download.mark, 'codicon codicon-warning');
  assert.equal(download.summary, 'Download failed at 17%');
  assert.equal(page.railItem('Download SDK').querySelector('.rail-summary').className, 'rail-summary failed');
});

test('Download SDK: an image on this computer or a running SDK', () => {
  const page = openPage();
  page.send(baseState({ ...SIGNED_IN, image: { status: 'present' } }));
  assert.equal(page.rail()[2].summary, 'v3.0.0.1 · downloaded');
  page.click(page.railItem('Download SDK'));
  assert.equal(page.lead(), 'Neat Studio found an SDK on this computer.');

  page.send(baseState({ ...SIGNED_IN, image: { status: 'present' }, containers: [{ name: 'neat-sdk', state: 'running' }] }));
  assert.equal(page.rail()[2].summary, 'v3.0.0.1 · already running');
});

test('Configure: Continue confirms it and opens Start Neat Studio with Start over', () => {
  const page = openPage();
  const downloaded = { ...SIGNED_IN, image: { status: 'present' } };
  page.send(baseState(downloaded));
  assert.equal(page.title(), 'Configure the SDK');
  assert.ok(page.shown(page.$('continue-button')));
  page.click(page.$('continue-button'));
  assert.equal(page.stepCount(), 'Step 5 of 5');
  assert.equal(page.title(), 'Start Neat Studio');
  assert.equal(page.lead(), 'Neat Studio starts the SDK container with your choices, then reopens VS Code inside it.');
  assert.ok(page.shown(page.$('reset')));
  assert.equal(page.shown(page.$('continue-button')), false, 'nothing after the last step');
  assert.equal(page.rail()[3].summary, 'No DevKit · No AI agent');
  assert.deepEqual(page.memory.value, { viewing: 'start', configConfirmed: true, checkConfirmed: true });
  assert.deepEqual(page.hostStatus().value, { active: 5, total: 5 });

  page.send(baseState({ ...downloaded, config: { ...baseState().config, devkitMode: 'pair', devkitIp: '192.168.1.20', codingAgents: 'install' } }));
  assert.equal(page.rail()[3].summary, '192.168.1.20 · Claude Code and Codex');

  page.send(baseState({ ...downloaded, containers: [{ name: 'neat-sdk', state: 'running' }] }));
  assert.equal(page.lead(), 'Your SDK is already running. Open Neat Studio inside it.');
});

test('Configure: Continue is disabled while a setting is invalid', () => {
  const page = openPage();
  page.send(baseState({ ...SIGNED_IN, image: { status: 'present' }, configErrors: { devkitIp: 'Enter an IP address.' } }));
  assert.equal(page.title(), 'Configure the SDK');
  assert.ok(page.shown(page.$('continue-button')));
  assert.equal(page.$('continue-button').disabled, true);
});

test('the page remembers a confirmed Configure step after it is reopened', () => {
  const page = openPage({ configConfirmed: true, checkConfirmed: true });
  page.send(baseState({ ...SIGNED_IN, image: { status: 'present' } }));
  assert.equal(page.title(), 'Start Neat Studio');
});

test('Check again keeps the page on Check this computer to show the new result', () => {
  const page = openPage();
  const failing = CHECKS_OK.map((i) => (i.id === 'daemon' ? { ...i, status: 'error' } : i));
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'error', items: failing } }));
  assert.equal(page.title(), 'Check this computer');
  page.click(page.$('prereq-recheck'));
  assert.deepEqual(page.actions().at(-1), { type: 'action', id: 'recheck' });

  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'checking', items: failing } }));
  page.send(baseState(SIGNED_IN));
  assert.equal(page.title(), 'Check this computer', 'did not jump to Download SDK');
  assert.equal(page.lead(), 'Everything the SDK needs is here. Hover a status icon to see why each item matters.');
  assert.deepEqual(page.hostStatus().value, { active: 3, total: 5 }, 'the side bar still knows the current step');
});

test('without pressing anything the page moves on to the current step', () => {
  const page = openPage();
  const failing = CHECKS_OK.map((i) => (i.id === 'daemon' ? { ...i, status: 'error' } : i));
  page.send(baseState({ ...SIGNED_IN, prereqs: { status: 'error', items: failing } }));
  assert.equal(page.title(), 'Check this computer');
  page.send(baseState(SIGNED_IN));
  assert.equal(page.title(), 'Download the SDK');
});

test('the step list opens done steps; steps ahead are not clickable', () => {
  const page = openPage();
  page.send(baseState(SIGNED_IN));
  assert.deepEqual(page.rail().map((r) => r.clickable), [true, true, false, false, false]);
  assert.equal(page.railItem('Sign in').title, 'Open this step');

  page.click(page.railItem('Sign in'));
  assert.equal(page.title(), 'Sign in to SiMa');
  assert.equal(page.rail()[0].viewing, true);
  assert.equal(page.rail()[0].clickable, false, 'the open step is not a link');

  page.click(page.railItem('Configure'));
  assert.equal(page.title(), 'Sign in to SiMa', 'a step ahead does not open');
});

test('after Start over the page goes back to the first step', () => {
  const page = openPage();
  page.send(baseState({ ...SIGNED_IN, image: { status: 'present' } }));
  page.click(page.$('continue-button'));
  assert.equal(page.title(), 'Start Neat Studio');

  page.send(baseState({ cli: { found: false }, image: { status: 'missing' } }));
  assert.equal(page.title(), 'Sign in to SiMa');
  assert.equal(page.memory.value.viewing, undefined);
});

test('one primary button per step', () => {
  const page = openPage();
  page.send(baseState());
  assert.deepEqual(page.primaryButtons(), ['Sign in to SiMa']);

  page.send(baseState(SIGNED_IN));
  assert.deepEqual(page.primaryButtons(), ['Download']);

  page.send(baseState({ ...SIGNED_IN, pull: { state: 'running', progress: { done: 1, total: 4 } } }));
  page.click(page.railItem('Download SDK'));
  assert.deepEqual(page.primaryButtons(), ['Continue'], 'Continue takes over from the step\'s buttons');
  assert.ok(page.$('pull-button').classList.contains('secondary') || !page.shown(page.$('pull-button')));

  page.click(page.railItem('Sign in'));
  assert.deepEqual(page.primaryButtons(), ['Continue'], 'signed in: the card\'s Continue');
});

test('a link with an action asks the extension for it', () => {
  const page = openPage();
  page.send(baseState());
  const link = page.doc.createElement('a');
  link.href = '#';
  link.dataset.linkAction = 'doctor';
  page.doc.body.appendChild(link);
  page.click(link);
  assert.deepEqual(page.actions().at(-1), { type: 'action', id: 'doctor' });
});
