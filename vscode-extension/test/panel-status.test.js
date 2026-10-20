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
