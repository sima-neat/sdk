'use strict';

// "Start over" on the setup page: removes what setup put on this computer so
// the steps can run again from the first one. It never touches the workspace
// folder. It doesn't use `sima-cli sdk remove`, which also deletes every
// unused Docker image on the machine, not only the SDK's.

const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const sdk = require('./sdk');
const container = require('./container');
const devcontainer = require('./devcontainer');

const SIMA_CLI_DIRS = process.platform === 'win32'
  ? [path.join(os.homedir(), '.sima-cli'), path.join(os.homedir(), '.sima-cli-env')]
  : [path.join(os.homedir(), '.sima-cli')];
const SDK_IMAGE = /(^|\/)sima-neat\/sdk[\w.-]*$/;

/** Neat SDK images, by tag, or by ID for untagged older versions. */
async function listSdkImages() {
  const result = await sdk.run('docker', ['images', '--format', '{{.Repository}}|{{.Tag}}|{{.ID}}|{{.Size}}']);
  if (result.code !== 0) {
    return [];
  }
  return result.stdout.trim().split('\n').filter(Boolean)
    .map((line) => {
      const [repository, tag, id, size] = line.split('|');
      return { repository, tag, id, size, ref: tag === '<none>' ? id : `${repository}:${tag}` };
    })
    .filter((image) => SDK_IMAGE.test(image.repository));
}

/** What a reset could remove, for the setup page. */
async function describe() {
  const [containers, images] = await Promise.all([sdk.listAllSdkContainers(), listSdkImages()]);
  return {
    containers: containers.map(({ name, state }) => ({ name, state })),
    images: images.map(({ ref, size }) => ({ ref, size })),
    simaCliInstalled: SIMA_CLI_DIRS.some((dir) => fs.existsSync(dir)),
    attachedTo: container.containerOfThisWindow(),
  };
}

function nameConfigsDir(context) {
  return path.dirname(devcontainer.nameConfigFile(context.globalStorageUri.fsPath, 'x'));
}

/**
 * Forgets this extension's settings and remembered state, and Dev Containers'
 * saved settings for SDK containers. Dev Containers' one-time trust answer is
 * its own and stays.
 */
async function forgetExtensionState(context) {
  const keys = Object.keys(context.extension.packageJSON.contributes.configuration.properties);
  const settings = vscode.workspace.getConfiguration();
  for (const key of keys) {
    if (settings.inspect(key).globalValue !== undefined) {
      await settings.update(key, undefined, vscode.ConfigurationTarget.Global);
    }
  }
  for (const key of context.globalState.keys().filter((k) => k.startsWith('simaNeat.'))) {
    await context.globalState.update(key, undefined);
  }
  const dir = nameConfigsDir(context);
  let removed = 0;
  try {
    for (const file of fs.readdirSync(dir).filter((f) => f.startsWith('ghcr.io-sima-neat-sdk') && f.endsWith('.json'))) {
      fs.rmSync(path.join(dir, file), { force: true });
      removed += 1;
    }
  } catch {
    // No saved Dev Containers settings yet.
  }
  return removed;
}

/**
 * Runs the chosen parts of a reset, in an order that works: containers before
 * their images, logout before sima-cli is removed. Returns what was done and
 * what failed; one failure doesn't stop the rest.
 */
async function run(context, choices, { simaCliFile, env, progress }) {
  const done = [];
  const failed = [];
  const step = async (message, action) => {
    progress.report({ message });
    try {
      const outcome = await action();
      if (outcome) {
        done.push(outcome);
      }
    } catch (error) {
      failed.push(`${message.replace(/…$/, '')}: ${error.message}`);
    }
  };
  const docker = async (args) => {
    const result = await sdk.run('docker', args, 300000);
    if (result.code !== 0) {
      throw new Error((result.stderr || result.stdout).trim().split('\n').pop());
    }
  };

  if (choices.containers) {
    for (const { name } of await sdk.listAllSdkContainers()) {
      await step(`Removing container ${name}…`, async () => {
        await docker(['rm', '-f', name]);
        return `Removed container ${name}`;
      });
    }
  }
  if (choices.images) {
    for (const { ref, size } of await listSdkImages()) {
      await step(`Removing image ${ref}…`, async () => {
        await docker(['rmi', ref]);
        return `Removed image ${ref} (${size})`;
      });
    }
  }
  if (choices.extensionState) {
    await step('Forgetting setup choices…', async () => {
      const configs = await forgetExtensionState(context);
      return `Forgot this extension's settings and progress${configs ? `, and Dev Containers' settings for ${configs} SDK container(s)` : ''}`;
    });
  }
  if ((choices.logout || choices.simaCli) && simaCliFile) {
    await step('Logging out of sima-cli…', async () => {
      await sdk.run(simaCliFile, ['logout'], 60000, env);
      await sdk.run(simaCliFile, ['--internal', 'logout'], 60000, env);
      return 'Logged out of sima-cli';
    });
  }
  if (choices.simaCli) {
    for (const dir of SIMA_CLI_DIRS.filter((d) => fs.existsSync(d))) {
      await step('Uninstalling sima-cli…', async () => {
        fs.rmSync(dir, { recursive: true, force: true });
        return `Removed ${dir}`;
      });
    }
  }
  return { done, failed };
}

module.exports = { describe, run, listSdkImages };
