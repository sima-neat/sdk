const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { SessionTime, parseDeadline, describe } = require('../src/session-time');

test('deadline protocol rejects ambiguous and malformed input', () => {
  for (const value of ['{}', 'null', '[]', '{"expiresAt":12}', '{"expiresAt":"2026-10-20T12:00:00"}', '{"expiresAt":"invalid"}']) {
    assert.throws(() => parseDeadline(value));
  }
  assert.equal(parseDeadline('{"expiresAt":null}'), null);
  assert.equal(parseDeadline('{"expiresAt":"2026-10-20T12:00:00Z"}'), Date.parse('2026-10-20T12:00:00Z'));
});

test('absolute deadline survives delayed ticks and clamps expiration', () => {
  assert.equal(describe(null), null);
  assert.equal(describe(3601000, 0).text, '1:00:01 remaining');
  assert.equal(describe(300001, 0).severity, 'normal');
  assert.equal(describe(300000, 0).severity, 'warning');
  assert.equal(describe(60000, 0).severity, 'error');
  assert.equal(describe(1, 0).text, '00:01 remaining');
  assert.equal(describe(0, 120000).seconds, 0);
});

test('file updates, extensions, invalid writes, clear, and disposal', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'neat-time-'));
  const file = path.join(dir, 'session.json');
  const notices = [];
  const states = [];
  const item = { show() { this.visible = true; }, hide() { this.visible = false; }, dispose() { this.disposed = true; } };
  const vscode = {
    StatusBarAlignment: { Left: 1 }, ThemeColor: class { constructor(id) { this.id = id; } },
    window: {
      createStatusBarItem: () => item,
      createOutputChannel: () => ({ appendLine() {}, dispose() {} }),
      showWarningMessage: (s) => notices.push(s), showErrorMessage: (s) => notices.push(s)
    }
  };
  const session = new SessionTime(vscode, file, s => states.push(s));
  clearInterval(session.timer);
  while (session.busy) await new Promise(resolve => setTimeout(resolve, 1));
  const write = async (seconds) => {
    await fs.writeFile(file + '.tmp', JSON.stringify({ expiresAt: new Date(Date.now() + seconds * 1000).toISOString() }));
    await fs.rename(file + '.tmp', file);
    await session.poll();
  };
  try {
    assert.equal(item.visible, false);
    assert.equal(states.at(-1), null);
    assert.equal(notices.length, 0);
    await write(240);
    assert.equal(item.visible, true);
    assert.equal(notices.length, 1);
    await session.poll();
    assert.equal(notices.length, 1);
    await fs.writeFile(file, '{broken');
    await session.poll();
    assert.equal(states.at(-1).severity, 'warning');
    await write(3600);
    assert.equal(states.at(-1).severity, 'normal');
    assert.equal(item.backgroundColor, undefined);
    await write(30);
    assert.equal(states.at(-1).severity, 'error');
    await write(-1);
    assert.equal(states.at(-1).seconds, 0);
    await session.poll();
    assert.equal(notices.length, 3);
    const expiresAt = new Date(Date.now() + 86400000).toISOString();
    for (const [display, expectedCount] of [['quiet', 3], ['warning', 4], ['urgent', 5], ['quiet', 5]]) {
      await fs.writeFile(file, JSON.stringify({ expiresAt, display }));
      await session.poll();
      await session.poll();
      assert.equal(notices.length, expectedCount);
      assert.equal(states.at(-1).display, display);
      if (display === 'quiet') assert.equal(item.backgroundColor, undefined);
    }
    await fs.writeFile(file, JSON.stringify({ expiresAt, display: 'warning', blink: true }));
    await session.poll();
    assert.equal(item.backgroundColor.id, 'statusBarItem.errorBackground');
    await session.poll();
    assert.equal(item.backgroundColor, undefined);
    assert.equal(item.visible, true);
    assert.match(item.text, /Neat: .*remaining$/);
    await session.poll();
    assert.equal(item.backgroundColor.id, 'statusBarItem.errorBackground');
    const beforeColorChange = notices.length;
    await fs.writeFile(file, JSON.stringify({ expiresAt, display: 'warning', blink: true, blinkColor: 'amber' }));
    await session.poll();
    assert.equal(item.backgroundColor.id, 'statusBarItem.warningBackground');
    await session.poll();
    assert.equal(item.backgroundColor, undefined);
    assert.equal(notices.length, beforeColorChange);
    const beforeToggle = notices.length;
    await fs.writeFile(file, JSON.stringify({ expiresAt, display: 'warning', blink: false }));
    await session.poll();
    await session.poll();
    assert.equal(item.backgroundColor.id, 'statusBarItem.warningBackground');
    assert.equal(notices.length, beforeToggle);
    await fs.writeFile(file, JSON.stringify({ expiresAt, display: 'quiet', blink: true }));
    await session.poll();
    await session.poll();
    assert.equal(item.backgroundColor, undefined);
    await fs.writeFile(file, '{"expiresAt":null}');
    await session.poll();
    assert.equal(item.visible, false);
    await write(600);
    await fs.unlink(file);
    await session.poll();
    assert.equal(item.visible, false);
  } finally {
    session.dispose();
    await session.poll();
    assert.equal(item.disposed, true);
    await fs.rm(dir, { recursive: true });
  }
});

test('host presentation is independent of remaining time', () => {
  const { parseSession } = require('../src/session-time');
  const expiresAt = '2026-10-21T18:00:00-07:00';
  assert.equal(parseSession(JSON.stringify({ expiresAt })).display, 'auto');
  assert.equal(parseSession(JSON.stringify({ expiresAt })).blink, false);
  assert.equal(parseSession(JSON.stringify({ expiresAt })).blinkColor, 'red');
  assert.throws(() => parseSession(JSON.stringify({ expiresAt, blinkColor: '#ff0000' })));
  assert.throws(() => parseSession(JSON.stringify({ expiresAt, blinkColor: null })));
  assert.throws(() => parseSession(JSON.stringify({ expiresAt, blink: 'true' })));
  assert.throws(() => parseSession(JSON.stringify({ expiresAt, display: 'bogus' })));
  const quiet = describe(30000, 0, 'quiet');
  assert.equal(quiet.severity, 'normal');
  assert.match(quiet.text, /^Expires .* UTC$/);
  assert.equal(describe(0, 1, 'quiet').severity, 'normal');
  assert.match(describe(0, 1, 'quiet').text, /^Expired /);
  assert.equal(describe(86400000, 0, 'warning').severity, 'warning');
  assert.equal(describe(86400000, 0, 'urgent').severity, 'error');
});
