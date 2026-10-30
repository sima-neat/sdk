const { execFile } = require('child_process');
const fs = require('fs/promises');
const path = require('path');
const {FALLBACK_STATE, parseState} = require('./registry-state');

function branchFor(model) {
  const branch = model.branch || 'develop';
  if (!['develop', 'main'].includes(branch)) throw new Error('Invalid model branch');
  return branch;
}

// Explicit routing also supports SDKs whose bundled CLI has no production default.
const MODEL_REGISTRY_ENV = {SIMA_MODELS_REGISTRY_BASE_URL: 'https://models-registry.neat.sima.ai'};

function parseCatalog(text) {
  const data = JSON.parse(text);
  if (!Array.isArray(data.models)) throw new Error('Invalid model registry response.');
  return data.models.flatMap(run => {
    const m = run.metadata || {};
    const id = m.model_id;
    const variant = m.build_profile_id || m.variant_id;
    if (![id, variant].every(v => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(v))) return [];
    return [{label: m.display_name || id, description: variant,
      detail: [m.description, (run.model_categories?.tasks || []).join(', '), m.license?.spdx].filter(Boolean).join(' · '), id, variant}];
  });
}

function runCli(file, args, token, timeout = 0, extraEnv = {}) {
  return new Promise((resolve, reject) => {
    if (token?.isCancellationRequested) return reject(new Error('Cancelled'));
    let cancellation;
    const child = execFile(file, args, {
      env: {...process.env, SIMA_CLI_CHECK_FOR_UPDATE: '0', NO_COLOR: '1', GIT_TERMINAL_PROMPT: '0', ...extraEnv},
      cwd: require('os').tmpdir(), maxBuffer: 32 * 1024 * 1024, timeout,
    }, (error, stdout, stderr) => {
      cancellation?.dispose();
      if (token?.isCancellationRequested) return reject(new Error('Cancelled'));
      if (error) {
        let message = (stderr || error.message).trim();
        for (const value of Object.values(extraEnv)) {
          if (typeof value === 'string' && value.startsWith('Authorization: Basic ')) {
            const encoded = value.slice('Authorization: Basic '.length);
            const secret = Buffer.from(encoded, 'base64').toString().split(':').slice(1).join(':');
            for (const sensitive of [value, encoded, secret]) if (sensitive) message = message.split(sensitive).join('[redacted]');
          }
        }
        return reject(new Error(message.slice(-3000)));
      }
      resolve(stdout);
    });
    cancellation = token?.onCancellationRequested(() => child.kill('SIGKILL'));
  });
}

function modelCardUrl(model) {
  const url = new URL('https://developer.sima.ai/models/');
  url.searchParams.set('branch', branchFor(model));
  url.searchParams.set('model', model.id);
  url.searchParams.set('variant', model.variant);
  return url.toString();
}

function downloadArgs(model, output) {
  return ['models', 'download', '--branch', branchFor(model), '--id', model.id,
    '--variant', model.variant, '--output', output, '--json'];
}

async function sourceRunner(vscode, run = runCli) {
  let session;
  try {
    session = await vscode.authentication.getSession('github', ['repo'], {createIfNone:true});
  } catch {
    throw new Error('Allow SiMa Neat to use your GitHub account in VSCode, then retry Copy model source folder. The account must have access to sima-neat/models.');
  }
  if (!session?.accessToken) throw new Error('GitHub sign-in was not completed. Retry Copy model source folder and allow account access.');
  // Process-only Git configuration: credentials never enter URLs, arguments, or files.
  const environment = {
    GIT_CONFIG_COUNT:'3',
    GIT_CONFIG_KEY_0:'http.https://github.com/.extraheader',
    GIT_CONFIG_VALUE_0:'Authorization: Basic ' + Buffer.from('x-access-token:' + session.accessToken).toString('base64'),
    GIT_CONFIG_KEY_1:'credential.helper', GIT_CONFIG_VALUE_1:'',
    GIT_CONFIG_KEY_2:'http.followRedirects', GIT_CONFIG_VALUE_2:'false',
    GIT_TRACE:'0', GIT_TRACE_CURL:'0', GIT_CURL_VERBOSE:'0',
  };
  return (file, args, token, timeout) => run(file, args, token, timeout, file === 'git' ? environment : {});
}

async function copySource(model, destination, token, run = runCli) {
  const temporary = await fs.mkdtemp(path.join(require('os').tmpdir(), 'neat-model-source-'));
  const repository = 'https://github.com/sima-neat/models.git';
  try {
    const checkout = path.join(temporary, 'repository');
    await run('git', ['clone', '--depth', '1', '--filter=blob:none', '--no-checkout',
      '--branch', branchFor(model), repository, checkout], token, 120000);
    const commit = (await run('git', ['-C', checkout, 'rev-parse', 'HEAD'], token)).trim();
    const archive = path.join(destination, 'source.tar');
    await run('git', ['-C', checkout, 'archive', '--format=tar', '--output', archive,
      'HEAD', `models/${model.id}`], token, 120000);
    await run('python3', [path.join(__dirname, 'unpack-model.py'), destination, archive], token);
    await fs.rm(archive);
    await fs.writeFile(path.join(destination, 'registry-source.json'),
      JSON.stringify({repository, branch:branchFor(model), commit, model:model.id,
        sourcePath:`models/${model.id}`}, null, 2) + '\n');
  } finally {
    await fs.rm(temporary, {recursive:true, force:true});
  }
}

function registerModels(vscode, context, resolveCli, enabled = false, getState = async () => FALLBACK_STATE) {
  let busy = false;
  const command = vscode.commands.registerCommand('simaNeat.browseModels', async () => {
    if (!enabled) return vscode.window.showInformationMessage('Model Registry requires SDK 3.0 or newer.');
    if (busy) return vscode.window.showInformationMessage('A model registry operation is already running.');
    busy = true;
    let destination;
    let completed = false;
    try {
      const state = await getState();
      const branch = state.current_state === null ? FALLBACK_STATE.default_branch : parseState(state).default_branch;
      const cli = await resolveCli();
      const models = await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,
        title:`Loading ${branch} model builds`, cancellable:true}, async (_, token) =>
        parseCatalog(await runCli(cli, ['models','list','--branch',branch,'--json'], token, 120000, MODEL_REGISTRY_ENV)));
      if (!models.length) return vscode.window.showInformationMessage(`No existing builds are available on ${branch}.`);
      const model = await vscode.window.showQuickPick(models, {title:`Model Registry · ${branch}`,
        placeHolder:'Search models, variants, tasks, or licenses', matchOnDescription:true, matchOnDetail:true});
      if (!model) return;
      model.branch = branch; // Keep the selected catalog branch for the whole operation.
      const operation = await vscode.window.showQuickPick([
        {label:'Download prebuilt artifact', action:'artifact', description:model.variant},
        {label:'Copy model source folder', action:'source', description:`Models repository · ${branch}`},
        {label:'Show Model Card', action:'card', description:`Open in VSCode · ${branch}`},
      ], {title:model.label, placeHolder:'Choose a model action'});
      if (!operation) return;
      if (operation.action === 'card') {
        await vscode.commands.executeCommand('simpleBrowser.show', modelCardUrl(model));
        return;
      }
      const source = operation.action === 'source';
      const workspace = await vscode.window.showWorkspaceFolderPick({placeHolder:'Select the workspace to receive the model folder'});
      if (!workspace) return;
      if (workspace.uri.scheme !== 'file') throw new Error('Open a filesystem workspace in the SDK to download models.');
      const action = await vscode.window.showInformationMessage(
        ` ${source ? "Copy source for" : "Download"} ${model.label} into ${workspace.name}/models?`.trim(),
        {modal:true, detail:`${model.detail}\n\n${source ? "Copies models/" + model.id + " from the current " + branch + " branch of sima-neat/models (may differ from the build revision)." : "Downloads the current existing " + branch + " build."} Files go into a new folder; no code is executed.`}, source ? 'Copy source' : 'Download');
      if (action !== (source ? 'Copy source' : 'Download')) return;
      const sourceRun = source ? await sourceRunner(vscode) : undefined;
      await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,
        title:`${source ? "Copying source for" : "Downloading"} ${model.label}`, cancellable:true}, async (progress, token) => {
        const root = path.join(workspace.uri.fsPath, 'models');
        await fs.mkdir(root, {recursive:true});
        const workspaceReal = await fs.realpath(workspace.uri.fsPath);
        const rootReal = await fs.realpath(root);
        if (!rootReal.startsWith(workspaceReal + path.sep)) throw new Error('The models folder points outside this workspace.');
        destination = await fs.mkdtemp(path.join(root, `${model.id}-${source ? "source" : model.variant}-`));
        if (source) {
          await copySource(model, destination, token, sourceRun);
          completed = true;
          return;
        }
        const result = JSON.parse(await runCli(cli, downloadArgs(model, destination), token, 0, MODEL_REGISTRY_ENV));
        if (typeof result.path !== 'string') throw new Error('The CLI did not return a downloaded path.');
        const downloaded = path.resolve(result.path);
        if (!downloaded.startsWith(destination + path.sep)) throw new Error('The CLI returned a path outside the download folder.');
        progress.report({message:'Preparing model files for review'});
        await runCli('python3', [path.join(__dirname, 'unpack-model.py'), destination, downloaded], token);
        await fs.writeFile(path.join(destination, 'registry-download.json'), JSON.stringify({...result, branch}, null, 2) + '\n');
        completed = true;
      });
      await vscode.commands.executeCommand('revealInExplorer', vscode.Uri.file(destination));
      vscode.window.showInformationMessage(`Model files ready in ${destination}`);
    } catch (error) {
      if (error.message !== 'Cancelled') vscode.window.showErrorMessage(`Model registry: ${error.message}`);
    } finally {
      if (destination && !completed) await fs.rm(destination, {recursive:true, force:true}).catch(() => {});
      busy = false;
    }
  });
  context.subscriptions.push(command);
}
module.exports = {parseCatalog, modelCardUrl, downloadArgs, runCli, sourceRunner, copySource, registerModels};
