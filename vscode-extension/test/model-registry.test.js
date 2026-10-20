const test = require('node:test');
const assert = require('node:assert/strict');
const {parseCatalog, downloadArgs, runCli} = require('../src/model-registry');
test('catalog exposes existing model variants and rejects unsafe identifiers', () => {
  const rows = parseCatalog(JSON.stringify({models:[
    {metadata:{model_id:'yolo',build_profile_id:'w8a8',display_name:'YOLO',description:'Detect objects',license:{spdx:'Apache-2.0'}},model_categories:{tasks:['detection']}},
    {metadata:{model_id:'../escape',variant_id:'x'}}, {metadata:{model_id:'pending'}}
  ]}));
  assert.equal(rows.length,1); assert.equal(rows[0].id,'yolo');
  assert.match(rows[0].detail,/detection/); assert.match(rows[0].detail,/Apache-2.0/);
  assert.deepEqual(downloadArgs(rows[0],'/workspace/my models'), ['models','download','--branch','develop','--stg','--id','yolo','--variant','w8a8','--output','/workspace/my models','--json']);
  assert.throws(()=>parseCatalog('{"models":{}}'));
});
test('CLI execution preserves arguments without shell expansion and reports failure', async () => {
  assert.equal(await runCli(process.execPath,['-e','process.stdout.write(process.argv[1])','$(echo unsafe)']), '$(echo unsafe)');
  await assert.rejects(runCli(process.execPath,['-e','process.stderr.write("failure");process.exit(2)']),/failure/);
});

test('download flow creates independent workspace folders and reveals results', async () => {
  const fs = require('node:fs/promises');
  const os = require('node:os');
  const path = require('node:path');
  const {registerModels} = require('../src/model-registry');
  const root = await fs.mkdtemp(path.join(os.tmpdir(),'neat-model-flow-'));
  try {
    const cli = path.join(root,'fake-cli');
    await fs.writeFile(cli, `#!${process.execPath}\nconst fs=require('fs'),p=require('path');
if(process.argv.includes('list')) console.log(JSON.stringify({models:[{metadata:{model_id:'model',variant_id:'w8a8',display_name:'Model'}}]}));
else {const root=process.argv[process.argv.indexOf('--output')+1];const folder=p.join(root,'model');fs.mkdirSync(folder);fs.writeFileSync(p.join(folder,'README.md'),'review');console.log(JSON.stringify({path:folder,run_id:'build-123'}));}\n`);
    await fs.chmod(cli,0o755);
    let callback;
    const revealed=[];
    const errors=[];
    const vscode={ProgressLocation:{Notification:1},Uri:{file:p=>p},commands:{
      registerCommand:(name,fn)=>{callback=fn;return {dispose(){}};},
      executeCommand:async(name,p)=>revealed.push(p)},window:{
      withProgress:async(options,fn)=>fn({report(){}}, {isCancellationRequested:false,onCancellationRequested:()=>({dispose(){}})}),
      showQuickPick:async rows=>rows[0],showWorkspaceFolderPick:async()=>({name:'test',uri:{scheme:'file',fsPath:root}}),
      showInformationMessage:async()=> 'Download',showErrorMessage:message=>errors.push(message)}};
    registerModels(vscode,{subscriptions:[]},async()=>cli, true);
    await callback();await callback();
    assert.deepEqual(errors,[]);assert.equal(revealed.length,2);assert.notEqual(revealed[0],revealed[1]);
    assert.equal(await fs.readFile(path.join(revealed[0],'model/README.md'),'utf8'),'review');
    assert.equal(JSON.parse(await fs.readFile(path.join(revealed[0],'registry-download.json'),'utf8')).run_id,'build-123');
  } finally {await fs.rm(root,{recursive:true,force:true});}
});

test('source action copies only the selected model and records its commit', async () => {
  const fs = require('node:fs/promises');
  const os = require('node:os');
  const path = require('node:path');
  const {copySource} = require('../src/model-registry');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'neat-source-test-'));
  try {
    const repo = path.join(root, 'repo');
    await fs.mkdir(path.join(repo, 'models/model'), {recursive:true});
    await fs.writeFile(path.join(repo, 'models/model/README.md'), 'Model source');
    await fs.writeFile(path.join(repo, 'unrelated.txt'), 'Do not copy');
    await runCli('git', ['init', '-b', 'develop', repo]);
    await runCli('git', ['-C', repo, 'add', '.']);
    await runCli('git', ['-C', repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'fixture']);
    const destination = path.join(root, 'output');
    await fs.mkdir(destination);
    let checkout;
    const runner = async (file, args, token, timeout) => {
      if (args[0] === 'clone') {
        assert.equal(args[args.length - 2], 'https://github.com/sima-neat/models.git');
        assert.equal(args[args.indexOf('--branch') + 1], 'develop');
        checkout = args[args.length - 1];
        args = [...args]; args[args.length - 2] = repo;
      }
      return runCli(file, args, token, timeout);
    };
    await copySource({id:'model'}, destination, undefined, runner);
    assert.equal(await fs.readFile(path.join(destination, 'contents/models/model/README.md'), 'utf8'), 'Model source');
    await assert.rejects(fs.stat(path.join(destination, 'contents/unrelated.txt')));
    await assert.rejects(fs.stat(checkout));
    const provenance = JSON.parse(await fs.readFile(path.join(destination, 'registry-source.json'), 'utf8'));
    assert.equal(provenance.commit, (await runCli('git', ['-C', repo, 'rev-parse', 'HEAD'])).trim());
    assert.equal(provenance.sourcePath, 'models/model');
    await assert.rejects(copySource({id:'missing'}, destination, undefined, runner));
    await assert.rejects(fs.stat(checkout));
  } finally { await fs.rm(root, {recursive:true, force:true}); }
});

test('source authentication uses VSCode session only in Git process environment', async () => {
  const {sourceRunner} = require('../src/model-registry');
  const calls=[];
  const vscode={authentication:{getSession:async(provider, scopes, options)=>{
    assert.equal(provider,'github');assert.deepEqual(scopes,['repo']);assert.equal(options.createIfNone,true);
    return {accessToken:'test-secret'};
  }}};
  const run = await sourceRunner(vscode, async (...args)=>calls.push(args));
  await run('git',['clone','https://github.com/sima-neat/models.git'],undefined,123);
  await run('git',['archive','HEAD'],undefined,123);
  await run('python3',['unpack-model.py'],undefined,123);
  for(const call of calls.slice(0,2)) {
    assert.equal(call[4].GIT_CONFIG_KEY_0,'http.https://github.com/.extraheader');
    assert.equal(call[4].GIT_CONFIG_VALUE_0,'Authorization: Basic '+Buffer.from('x-access-token:test-secret').toString('base64'));
    assert.ok(!JSON.stringify(call.slice(0,4)).includes('test-secret'));
  }
  assert.deepEqual(calls[2][4],{});
  await assert.rejects(sourceRunner({authentication:{getSession:async()=>{throw Error('denied');}}}), /Allow SiMa Neat/);
  await assert.rejects(sourceRunner({authentication:{getSession:async()=>undefined}}), /not completed/);
});

test('Git errors redact session credentials', async () => {
  const header='Authorization: Basic '+Buffer.from('x-access-token:secret-test-value').toString('base64');
  await assert.rejects(runCli(process.execPath,['-e',
    'process.stderr.write(process.env.GIT_CONFIG_VALUE_0+" secret-test-value");process.exit(1)'],undefined,0,
    {GIT_CONFIG_VALUE_0:header}), error=>!error.message.includes('secret-test-value') && !error.message.includes(header) && error.message.includes('[redacted]'));
});

test('Show Model Card opens selected develop model inside VSCode without a workspace', async () => {
  const {modelCardUrl, registerModels} = require('../src/model-registry');
  const url=new URL(modelCardUrl({id:'model with space',variant:'w8&a8'}));
  assert.equal(url.origin,'https://developer-stg.sima.ai');
  assert.equal(url.pathname,'/models/');
  assert.equal(url.searchParams.get('model'),'model with space');
  assert.equal(url.searchParams.get('variant'),'w8&a8');
  assert.equal(url.searchParams.get('branch'),'develop');
  let callback;
  const opened=[];
  const vscode={ProgressLocation:{Notification:1},commands:{
    registerCommand:(id,fn)=>{callback=fn;return {dispose(){}};},
    executeCommand:async(...args)=>opened.push(args)},window:{
    withProgress:async()=>[{id:'qwen3_5_0_8b',variant:'w4a16',label:'Qwen'}],
    showQuickPick:async(rows)=>rows.find(row=>row.action==='card') || rows[0],
    showWorkspaceFolderPick:()=>assert.fail('Model card should not require a workspace'),
    showErrorMessage:message=>assert.fail(message)}};
  registerModels(vscode,{subscriptions:[]},async()=>'/unused/cli', true);
  await callback();
  assert.deepEqual(opened,[['simpleBrowser.show','https://developer-stg.sima.ai/models/?branch=develop&model=qwen3_5_0_8b&variant=w4a16']]);
});
