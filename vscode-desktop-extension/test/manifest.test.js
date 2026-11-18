'use strict';

// package.json and README as VS Code shows them: the extension as "Neat Studio",
// its icons, the host side bar view, the "Studio: Set up SDK" command, and the
// files the README and the manifest point to.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { ROOT } = require('./helpers');

const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const exists = (relative) => fs.existsSync(path.join(ROOT, relative));

test('the extension is called Neat Studio and keeps its ID', () => {
  assert.equal(manifest.displayName, 'Neat Studio');
  assert.equal(`${manifest.publisher}.${manifest.name}`, 'sima-neat.sima-neat-desktop');
  assert.equal(manifest.description, 'DevKits, examples on DevKit, Model Registry and Insight for SiMa developers.');
  assert.equal(manifest.icon, 'media/marketplace/icon.png');
  assert.ok(exists(manifest.icon));
});

test('the activity bar shows Neat Studio with the circuit board icon', () => {
  const [container] = manifest.contributes.viewsContainers.activitybar;
  assert.deepEqual(container, { id: 'simaNeatTools', title: 'Neat Studio', icon: 'media/studio/circuit-board.svg' });
  assert.ok(exists(container.icon));
});

test('the host view shows on this computer, the Palette only inside the SDK', () => {
  const views = manifest.contributes.views.simaNeatTools;
  assert.deepEqual(views.map((v) => [v.id, v.name, v.type, v.when]), [
    ['simaNeatTools.host', 'Neat Studio', 'webview', '!remoteName'],
    ['simaNeatTools.panel', 'Palette', 'webview', 'remoteName'],
  ]);
  assert.ok(manifest.activationEvents.includes('onView:simaNeatTools.host'));
});

test('the setup command is "Studio: Set up SDK"', () => {
  const command = manifest.contributes.commands.find((c) => c.command === 'simaNeat.openSetup');
  assert.equal(`${command.category}: ${command.title}`, 'Studio: Set up SDK');
});

test('README images and the files the pages load are in the package', () => {
  const readme = fs.readFileSync(path.join(ROOT, 'README.md'), 'utf8');
  const images = [...readme.matchAll(/src="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(images.length > 0);
  for (const image of images) {
    assert.ok(exists(image), `${image} exists`);
  }
  for (const file of ['media/codicons/codicon.css', 'media/codicons/codicon.ttf', 'media/setup.html', 'media/setup.js', 'media/setup.css']) {
    assert.ok(exists(file), `${file} exists`);
  }
  const css = fs.readFileSync(path.join(ROOT, 'media', 'codicons', 'codicon.css'), 'utf8');
  for (const font of css.matchAll(/url\("?([^")?#]+)/g)) {
    assert.ok(exists(path.join('media', 'codicons', font[1])), `codicon font ${font[1]} exists`);
  }
});

test('README image links on the Marketplace point at the commit in package script', () => {
  assert.match(manifest.scripts.package, /--baseImagesUrl https:\/\/raw\.githubusercontent\.com\/sima-neat\/sdk\/[0-9a-f]{40}\/vscode-desktop-extension\/$/);
});

test('tests and dev tools stay out of the .vsix', () => {
  const ignore = fs.readFileSync(path.join(ROOT, '.vscodeignore'), 'utf8').split(/\r?\n/);
  assert.ok(ignore.includes('node_modules/**'));
  assert.ok(ignore.includes('test/**'));
  assert.deepEqual(Object.keys(manifest.dependencies || {}), [], 'the extension ships without npm packages');
});
