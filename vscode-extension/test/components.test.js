const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { validateCatalog, resolveCatalog, fetchCatalog, downloadArtifact, ComponentCatalog } = require('../src/components');
const original = require('../../components.json');
const candidate = () => {
  const catalog = structuredClone(original);
  catalog.sdks['3.0.0'].status = 'candidate';
  return catalog;
};
const options = { release: 'v3.0.0.0', arch: 'arm64', codeServer: '4.144.0', vscode: '1.144.0' };
function qualified() {
  const catalog = candidate(), row = catalog.sdks['3.0.0'];
  row.status = 'qualified';
  return catalog;
}
test('candidate releases require explicit testing, and platform identity cannot select a development SDK', () => {
  assert.throws(() => resolveCatalog(candidate(), options), /candidate/);
  assert.equal(resolveCatalog(candidate(), {...options, allowCandidate: true}).components.codex.version, original.sdks['3.0.0'].components.codex.version);
  assert.throws(() => resolveCatalog(qualified(), {...options, release: 'develop-1234567'}), /No compatible/);
  assert.equal(resolveCatalog(candidate(), {...options, release: 'develop-1234567', testVersion: '3.0.0', allowCandidate: true}).status, 'candidate');
});
test('matching is exact for SDK release, engine pair and architecture', () => {
  const c = qualified();
  assert.equal(resolveCatalog(c, options).sdkVersion, '3.0.0');
  for (const release of ['3.0.0.1', 'v3.0.0.1']) {
    const selected = resolveCatalog(c, {...options, release});
    assert.equal(selected.sdkVersion, '3.0.0');
    assert.equal(selected.sdkFallback, false);
    assert.deepEqual(selected.components, c.sdks['3.0.0'].components);
  }
  for (const change of [{release:'v3.0.0.2'}, {arch:'riscv64'}, {codeServer:'4.137.0'}, {vscode:'1.140.0'}])
    assert.throws(() => resolveCatalog(c, {...options, ...change}));
  c.sdks['3.1.0'] = structuredClone(c.sdks['3.0.0']); c.sdks['3.1.0'].sdk_releases=['3.1.0'];
  assert.equal(resolveCatalog(c, {...options, release:'v3.1.0'}).sdkVersion,'3.1.0');
  c.sdks['3.0.0'].status = 'revoked';
  assert.throws(() => resolveCatalog(c, {...options, allowCandidate:true}), /revoked/);
});
test('panel SDK fallback uses default pins for unmapped releases and preserves exact pins', () => {
  const catalog = qualified();
  for (const release of ['v3.0.0.2', 'v3.1.0', 'develop-1234567', undefined]) {
    const selected = resolveCatalog(catalog, {...options, release, allowSdkFallback: true});
    assert.equal(selected.sdkFallback, true);
    assert.equal(selected.sdkRelease, release);
    assert.equal(selected.sdkVersion, catalog.build_sdk_version);
    assert.deepEqual(selected.components, catalog.sdks[catalog.build_sdk_version].components);
  }
  const exact = resolveCatalog(catalog, {...options, allowSdkFallback: true});
  assert.equal(exact.sdkFallback, false);
  catalog.sdks['3.1.0'] = structuredClone(catalog.sdks['3.0.0']);
  catalog.sdks['3.1.0'].sdk_releases = ['3.1.0'];
  catalog.sdks['3.1.0'].components.codex.version = '1.2.3';
  assert.equal(resolveCatalog(catalog, {...options, release: '3.1.0', allowSdkFallback: true}).components.codex.version, '1.2.3');
  catalog.sdks['3.1.0'].status = 'revoked';
  assert.throws(() => resolveCatalog(catalog, {...options, release: '3.1.0', allowSdkFallback: true}), /revoked/);
  catalog.sdks['3.1.0'].status = 'candidate';
  const candidate = resolveCatalog(catalog, {...options, release: '3.1.0', allowSdkFallback: true});
  assert.equal(candidate.sdkFallback, true);
  assert.equal(candidate.status, 'candidate');
  assert.equal(candidate.components.codex.version, '1.2.3');
});
test('panel candidate fallback needs no test flags and preserves engine, architecture and revocation checks', () => {
  const fallbackOptions = {...options, release: 'develop-test', allowSdkFallback: true};
  for (const release of ['v3.0.0.0', 'v3.0.0.1', 'develop-test']) {
    const selected = resolveCatalog(candidate(), {...fallbackOptions, release});
    assert.equal(selected.sdkFallback, true);
    assert.equal(selected.status, 'candidate');
    assert.deepEqual(selected.components, original.sdks['3.0.0'].components);
  }
  for (const change of [{arch: 'riscv64'}, {codeServer: '4.137.0'}, {vscode: '1.140.0'}])
    assert.throws(() => resolveCatalog(candidate(), {...fallbackOptions, ...change}), /not been qualified/);
  const revoked = candidate();
  revoked.sdks['3.0.0'].status = 'revoked';
  assert.throws(() => resolveCatalog(revoked, fallbackOptions), /revoked/);
  assert.throws(() => resolveCatalog(candidate(), {...options}), /candidate/);
  assert.throws(() => resolveCatalog(qualified(), {...fallbackOptions, testVersion: '9.0.0', allowCandidate: true}), /No compatible/);
  assert.equal(resolveCatalog(candidate(), {...fallbackOptions, testVersion: '3.0.0', allowCandidate: true}).sdkFallback, false);
});
test('artifact integrity, supported status and trusted locations are mandatory', () => {
  for (const mutate of [c=>c.schema_version=2, c=>delete c.sdks['3.0.0'].components.claude.artifacts.arm64,
    c=>c.sdks['3.0.0'].components.codex.id='other.agent',
    c=>c.sdks['3.0.0'].components.codex.artifacts.amd64.url='http://localhost/evil',
    c=>c.sdks['3.0.0'].components.codex.artifacts.amd64.sha256='bad',
    c=>c.sdks['3.0.0'].status='untested']) {
    const c=qualified(); mutate(c); assert.throws(()=>validateCatalog(c));
  }
});
test('malformed online catalogs are distinguished from outages and cannot trigger stale fallback', async () => {
  await assert.rejects(fetchCatalog(async()=>new Response('{bad json')),
    error=>error.invalidCatalog === true);
});
test('downloads verify checksums and recheck cached bytes before reuse', async t => {
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'sdk-components-download-'));
  t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const content=Buffer.from('test artifact'), sha=crypto.createHash('sha256').update(content).digest('hex');
  const item={url:'https://open-vsx.org/test.vsix',sha256:sha};let requests=0;
  const fetcher=async()=>{requests++;return new Response(content);};
  const file=await downloadArtifact(item,dir,fetcher);
  await downloadArtifact(item,dir,fetcher);assert.equal(requests,1);
  await fs.writeFile(file,'corrupted cache');await downloadArtifact(item,dir,fetcher);assert.equal(requests,2);
  await assert.rejects(downloadArtifact({...item,sha256:'f'.repeat(64)},dir,fetcher),/checksum/);
  assert.equal((await fs.readdir(dir)).length,1);
});
test('online revocation and invalid manifests block installs, while network outages reuse validated offline data', async t => {
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'sdk-components-cache-'));
  t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  let c=qualified(), offline=false;
  const service=new ComponentCatalog({globalStorageUri:{fsPath:dir},extensionPath:dir},{
    releaseText:'SDK Release = v3.0.0.0',codeServer:'4.144.0',vscodeVersion:'1.144.0',
    execute:async()=>({stdout:'codex-cli 0.153.4'}),fetchCatalog:async()=>{if(offline)throw Error('offline');return c;},
  });
  assert.equal((await service.refresh()).available,true);
  offline=true;assert.equal((await service.refresh()).source,'offline');
  offline=false;c={schema_version:2};assert.equal((await service.refresh()).available,false);
  c=qualified();c.sdks['3.0.0'].status='revoked';assert.equal((await service.refresh()).available,false);
  offline=true;assert.equal((await service.refresh()).available,false);
});
test('engine detection reads installed metadata without spawning code-server inside the extension host',async t=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'sdk-components-engine-'));
 t.after(()=>fs.rm(dir,{recursive:true,force:true}));
 const file=path.join(dir,'package.json');await fs.writeFile(file,JSON.stringify({version:'4.144.0'}));
 const service=new ComponentCatalog({globalStorageUri:{fsPath:dir},extensionPath:dir},{
  releaseText:'SDK Release = v3.0.0.0',serverVersionFile:file,vscodeVersion:'1.144.0',fetchCatalog:async()=>qualified(),
  execute:async(name)=>{assert.equal(name,'codex');return {stdout:'codex-cli 0.153.4'};},
 });
 assert.equal((await service.refresh()).available,true);
});
test('a newer or rejected online policy cannot be replaced with stale cached qualification',async t=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'sdk-components-revision-'));
 t.after(()=>fs.rm(dir,{recursive:true,force:true}));
 let catalog=qualified(),offline=false;catalog.revision=original.revision+1;
 const service=new ComponentCatalog({globalStorageUri:{fsPath:dir},extensionPath:dir},{
  releaseText:'SDK Release = v3.0.0.0',codeServer:'4.144.0',vscodeVersion:'1.144.0',execute:async()=>({stdout:'codex-cli 0.153.4'}),
  fetchCatalog:async()=>{if(offline)throw Error('network');return catalog;},
 });
 assert.equal((await service.refresh()).available,true);
 catalog=qualified();assert.equal((await service.refresh()).available,false);
 offline=true;assert.equal((await service.refresh()).available,false);
});
test('tagged image builds require a qualified matching cohort while development builds remain testable',async t=>{
 const {spawnSync}=require('node:child_process');
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'sdk-components-release-'));
 t.after(()=>fs.rm(dir,{recursive:true,force:true}));
 const file=path.join(dir,'components.json');
 const command=path.resolve(__dirname,'../../scripts/components-catalog.js');
 await fs.writeFile(file,JSON.stringify(candidate()));
 assert.notEqual(spawnSync(process.execPath,[command,'check-release',file,'v3.0.0.0']).status,0);
 assert.equal(spawnSync(process.execPath,[command,'check-release',file,'develop-test']).status,0);
 await fs.writeFile(file,JSON.stringify(qualified()));
 assert.equal(spawnSync(process.execPath,[command,'check-release',file,'v3.0.0.0']).status,0);
 assert.notEqual(spawnSync(process.execPath,[command,'check-release',file,'v3.1.0']).status,0);
 await fs.writeFile(file,JSON.stringify(original));
 assert.equal(spawnSync(process.execPath,[command,'check-release',file,'v3.0.0.1']).status,0);
});

test('qualified runtime mappings do not require embedded qualification records',()=>{
 const catalog=qualified();
 assert.equal(Object.hasOwn(catalog.sdks['3.0.0'],'qualification'),false);
 assert.equal(resolveCatalog(catalog,options).status,'qualified');
});

test('installed profile must match both version and persistent update pin', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'sdk-pins-'));
  try {
    const service = new ComponentCatalog({globalStorageUri: {fsPath: dir}, extensionPath: path.join(dir, 'sima-neat')});
    const target = {id: 'openai.chatgpt', version: '1.2.3'};
    for (const entry of [
      {identifier: {id: target.id}, version: target.version},
      {identifier: {id: target.id}, version: target.version, metadata: {pinned: false}},
      {identifier: {id: target.id}, version: '9.9.9', metadata: {pinned: true}},
    ]) {
      await fs.writeFile(path.join(dir, 'extensions.json'), JSON.stringify([entry]));
      await assert.rejects(service.verifyInstalled(target), /did not pin/);
      assert.equal(service.isPinned(target), false);
    }
    await fs.writeFile(path.join(dir, 'extensions.json'), JSON.stringify([
      {identifier: {id: target.id}, version: target.version, metadata: {pinned: true}},
    ]));
    await service.verifyInstalled(target);
    assert.equal(service.isPinned(target), true);
    await fs.rm(path.join(dir, 'extensions.json'));
    await service.readInstalledProfile();
    assert.equal(service.isPinned(target), false);
  } finally { await fs.rm(dir, {recursive: true, force: true}); }
});

test('offline cold starts use bundled policy, and restarts retain the last validated cached policy', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'sdk-offline-start-'));
  t.after(() => fs.rm(dir, {recursive: true, force: true}));
  const context = {globalStorageUri: {fsPath: path.join(dir, 'storage')}, extensionPath: path.join(dir, 'extension')};
  await fs.mkdir(context.extensionPath);
  await fs.writeFile(path.join(context.extensionPath, 'components.json'), JSON.stringify(qualified()));
  const config = {releaseText: 'SDK Release = v3.0.0.0', codeServer: '4.144.0', vscodeVersion: '1.144.0',
    execute: async () => ({stdout: 'codex-cli 0.153.4'}), fetchCatalog: async () => {throw Error('No internet');}};
  const cold = await new ComponentCatalog(context, config).refresh();
  assert.equal(cold.available, true);
  assert.equal(cold.source, 'offline');
  const updated = qualified();
  updated.revision++;
  await new ComponentCatalog(context, {...config, fetchCatalog: async () => updated}).refresh();
  await fs.rm(path.join(context.extensionPath, 'components.json'));
  const restarted = await new ComponentCatalog(context, config).refresh();
  assert.equal(restarted.available, true);
  assert.equal(restarted.source, 'offline');
  assert.equal(restarted.components.codex.version, updated.sdks['3.0.0'].components.codex.version);
});

test('offline installs reuse checksum-verified cached packages and immediately reject missing or corrupt ones', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'sdk-offline-vsix-'));
  t.after(() => fs.rm(dir, {recursive: true, force: true}));
  const contents = Buffer.from('cached VSIX fixture');
  const item = {url: 'https://open-vsx.org/cached.vsix', sha256: crypto.createHash('sha256').update(contents).digest('hex')};
  let requests = 0;
  const fetcher = async () => {requests++; return new Response(contents);};
  const offline = () => downloadArtifact(item, dir, fetcher, '.vsix', {cacheOnly: true});
  await assert.rejects(offline(), {code: 'OFFLINE_ARTIFACT_UNAVAILABLE'});
  assert.equal(requests, 0);
  const file = await downloadArtifact(item, dir, fetcher);
  assert.equal(await offline(), file);
  assert.equal(requests, 1);
  await fs.writeFile(file, 'corrupted cache');
  await assert.rejects(offline(), {code: 'OFFLINE_ARTIFACT_UNAVAILABLE'});
  assert.equal(requests, 1);
});

test('panel candidate fallback prepares cached pinned artifacts offline without downloading', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'sdk-offline-prepare-'));
  t.after(() => fs.rm(dir, {recursive: true, force: true}));
  const catalog = candidate();
  const target = catalog.sdks['3.0.0'].components.codex;
  const contents = Buffer.from('offline package fixture');
  const sha256 = crypto.createHash('sha256').update(contents).digest('hex');
  for (const arch of ['amd64', 'arm64']) target.artifacts[arch].sha256 = sha256;
  const context = {globalStorageUri: {fsPath: path.join(dir, 'storage')}, extensionPath: path.join(dir, 'extension')};
  await fs.mkdir(context.extensionPath);
  await fs.writeFile(path.join(context.extensionPath, 'components.json'), JSON.stringify(catalog));
  const packages = path.join(context.globalStorageUri.fsPath, 'component-artifacts');
  await fs.mkdir(packages, {recursive: true});
  const file = path.join(packages, sha256 + '.vsix');
  await fs.writeFile(file, contents);
  const service = new ComponentCatalog(context, {
    releaseText: 'SDK Release = develop-test', codeServer: '4.144.0', vscodeVersion: '1.144.0', allowSdkFallback: true,
    fetchCatalog: async () => {throw Error('No internet');},
    execute: async name => ({stdout: name === 'codex' ? 'codex-cli 0.153.4' :
      JSON.stringify({publisher: 'openai', name: 'chatgpt', version: target.version})}),
  });
  assert.equal((await service.artifact('codex')).file, file);
  assert.equal(service.snapshot().source, 'offline');
  assert.equal(service.snapshot().sdkFallback, true);
  assert.equal(service.snapshot().status, 'candidate');
  await fs.rm(file);
  await assert.rejects(service.artifact('codex'), {code: 'OFFLINE_ARTIFACT_UNAVAILABLE'});
});
