const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {loadStatuses} = require('../src/panel-status');
const tick = () => new Promise(resolve => setImmediate(resolve));

test('independent checks finish while one stalls; timeout ignores late results', async () => {
  let release;
  const updates = [];
  const pending = loadStatuses({slow: () => new Promise(r => {release = r;}),
    fast: async () => ({status:'ready'}), broken: () => {throw new Error('private details');}},
    (key, state) => updates.push({key, state}), 25);
  await tick();
  assert.equal(updates.find(x => x.key === 'fast').state.status, 'ready');
  assert.equal(updates.some(x => x.key === 'slow'), false);
  await pending;
  assert.equal(updates.find(x => x.key === 'slow').state.disabled, true);
  assert.equal(updates.find(x => x.key === 'broken').state.buttonLabel, 'Status unavailable');
  release({status:'late'});
  await tick();
  assert.equal(updates.length, 3);
});

function providerHarness() {
  const source = fs.readFileSync(require.resolve('../src/extension'), 'utf8');
  const requests = [];
  const context = {vscode:{Uri:{joinPath:()=>''}},
    getWorkspaceRoot:()=>'', getSamplesState:async()=>({}), getTutorialsState:async()=>({}),
    getDeveloperPortalAuthState:async()=>({}), getDevKitSyncState:async()=>({}),
    getPanelHtml:(_logo, samples)=>JSON.stringify(samples),
    loadStatuses:(_probes, update)=>new Promise(resolve=>requests.push({update, resolve}))};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('class NeatPanelProvider'), source.indexOf('async function activate')) + '\nthis.Provider = NeatPanelProvider;', context);
  const provider = new context.Provider('');
  const messages = [];
  const webview = {html:'', asWebviewUri:()=>'', postMessage:m=>messages.push(m)};
  provider.webviewView = {webview};
  return {provider, requests, messages, webview};
}

test('panel renders before probes finish and updates without reloading its document', async () => {
  const {provider, requests, messages, webview} = providerHarness();
  const pending = provider.refresh();
  const initial = webview.html;
  assert.match(initial, /Checking/);
  requests[0].update('samples', {status:'ready'});
  assert.equal(webview.html, initial);
  assert.equal(messages[0].section, 'samples');
  assert.match(messages[0].html, /ready/);
  requests[0].resolve(); await pending;
});

test('old refreshes and disposed providers cannot publish stale results', async () => {
  const {provider, requests, messages} = providerHarness();
  const first = provider.refresh(); const second = provider.refresh();
  requests[0].update('samples', {status:'stale'});
  assert.equal(messages.length, 0);
  requests[1].update('samples', {status:'fresh'});
  assert.equal(messages.length, 1);
  provider.dispose();
  requests[1].update('samples', {status:'disposed'});
  assert.equal(messages.length, 1);
  requests.forEach(r => r.resolve()); await Promise.all([first, second]);
});

test('webview resolution returns while status probes are pending', async () => {
  const {provider, requests, webview} = providerHarness();
  webview.onDidReceiveMessage = () => ({dispose(){}});
  await provider.resolveWebviewView({webview});
  assert.equal(requests.length, 1);
  assert.match(webview.html, /Checking/);
  requests[0].resolve();
});

test('updated section buttons use delegated handlers and preserve other sections', () => {
  const source = fs.readFileSync(require.resolve('../src/extension'), 'utf8');
  const ctx = {modelsEnabled:false};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('function getPanelHtml('), source.indexOf('function deactivate()')), ctx);
  const state = {disabled:true, buttonLabel:'Loading', status:'Checking', detail:''};
  const html = ctx.getPanelHtml({scheme:'https'}, state, state, state, state);
  assert.match(html, /id="developerPortalAuth"[^>]*disabled/);
  const handlers = {};
  const sent = [];
  const replaced = [];
  const page = {
    acquireVsCodeApi:()=>({postMessage:m=>sent.push(m)}),
    window:{addEventListener:(name,fn)=>handlers[name]=fn},
    document:{addEventListener:(name,fn)=>handlers[name]=fn,
      getElementById:id=>({replaceWith:()=>replaced.push(id)})},
    DOMParser:class {parseFromString(){return {getElementById:id=>({id})};}}
  };
  vm.createContext(page);
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], page);
  handlers.message({data:{command:'panelStatus',html:'updated',section:'samples'}});
  assert.deepEqual(replaced, ['status-samples']);
  const button = {id:'cloneSamples', disabled:false, dataset:{}};
  handlers.click({target:{closest:()=>button}});
  assert.equal(sent.at(-1).command, 'cloneSamples');
  assert.equal(button.disabled, true);
  handlers.click({target:{closest:()=>({id:'refreshStatus',dataset:{}})}});
  assert.equal(sent.at(-1).command, 'refreshStatus');
});

test('interactive login Python helper is not constrained by the status probe deadline', async () => {
  const source = fs.readFileSync(require.resolve('../src/extension'), 'utf8');
  const calls = [];
  let finishImport;
  const context = {
    SIMA_CLI_PYTHON_CANDIDATE_PATHS: ['/fallback/python'],
    resolveSimaCliPythonExecutable: async () => '/sdk/python',
    execFilePromise: (file, args, options) => {
      calls.push({file, args, options});
      return new Promise(resolve => {finishImport = resolve;});
    }
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function execPythonSnippet('),
    source.indexOf('async function resolveSimaCliExecutable(')), context);
  const pending = context.execPythonSnippet('import slow_auth; print("ready")');
  await tick();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].file, '/sdk/python');
  assert.equal(calls[0].options.timeout, undefined);
  assert.equal(calls[0].options.killSignal, undefined);
  finishImport('ready');
  assert.equal(await pending, 'ready');
  assert.equal(calls.length, 1);
});

// Both sidebar and landing page must keep the shared offline Insight resolver,
// while sidebar subprocesses retain this PR's hard termination deadline.
test('sidebar Insight lookup keeps offline resolution and a hard process deadline', async () => {
  const source = fs.readFileSync(require.resolve('../src/extension'), 'utf8');
  const {readNeatStatus} = require('../src/landing-data');
  const calls = [];
  const context = {
    readNeatStatus,
    getInsightUrl: async status => status.insight.webUiUrl,
    execFilePromise: async (file, args, options, uiOptions) => {
      calls.push({file, args, options, uiOptions});
      return JSON.stringify({insight: {webUiUrl: 'http://localhost:9900'}});
    }
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function getInsightWebUiUrl('),
    source.indexOf('async function getDevKitSyncState(')), context);
  assert.equal(await context.getInsightWebUiUrl(), 'http://localhost:9900');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].file, 'neat');
  assert.deepEqual(calls[0].args, ['--json', '--offline']);
  assert.equal(calls[0].options.timeout, 5000);
  assert.equal(calls[0].options.killSignal, 'SIGKILL');
  assert.equal(calls[0].uiOptions.showError, false);
});
