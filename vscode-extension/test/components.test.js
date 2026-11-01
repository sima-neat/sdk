const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { validateCatalog, resolveCatalog, fetchCatalog, downloadArtifact, ComponentCatalog } = require('../src/components');
const original = require('../../components.json');
const clone = () => structuredClone(original);
const options = { release: 'v3.0.0.0', arch: 'arm64', codeServer: '4.144.0', vscode: '1.144.0' };
function qualified() {
  const catalog = clone(), row = catalog.sdks['3.0.0'];
  row.status = 'qualified';
  return catalog;
}
test('candidate releases require explicit testing, and platform identity cannot select a development SDK', () => {
  assert.throws(() => resolveCatalog(clone(), options), /candidate/);
  assert.equal(resolveCatalog(clone(), {...options, allowCandidate: true}).components.codex.version, original.sdks['3.0.0'].components.codex.version);
  assert.throws(() => resolveCatalog(qualified(), {...options, release: 'develop-1234567'}), /No compatible/);
  assert.equal(resolveCatalog(clone(), {...options, release: 'develop-1234567', testVersion: '3.0.0', allowCandidate: true}).status, 'candidate');
});
test('matching is exact for SDK release, engine pair and architecture', () => {
  const c = qualified();
  assert.equal(resolveCatalog(c, options).sdkVersion, '3.0.0');
  for (const change of [{release:'v3.0.0.1'}, {arch:'riscv64'}, {codeServer:'4.137.0'}, {vscode:'1.140.0'}])
    assert.throws(() => resolveCatalog(c, {...options, ...change}));
  c.sdks['3.1.0'] = structuredClone(c.sdks['3.0.0']); c.sdks['3.1.0'].sdk_releases=['3.1.0'];
  assert.equal(resolveCatalog(c, {...options, release:'v3.1.0'}).sdkVersion,'3.1.0');
  c.sdks['3.0.0'].status = 'revoked';
  assert.throws(() => resolveCatalog(c, {...options, allowCandidate:true}), /revoked/);
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
 await fs.writeFile(file,JSON.stringify(clone()));
 assert.notEqual(spawnSync(process.execPath,[command,'check-release',file,'v3.0.0.0']).status,0);
 assert.equal(spawnSync(process.execPath,[command,'check-release',file,'develop-test']).status,0);
 await fs.writeFile(file,JSON.stringify(qualified()));
 assert.equal(spawnSync(process.execPath,[command,'check-release',file,'v3.0.0.0']).status,0);
 assert.notEqual(spawnSync(process.execPath,[command,'check-release',file,'v3.1.0']).status,0);
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
