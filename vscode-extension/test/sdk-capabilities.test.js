const test = require('node:test');
const assert = require('node:assert/strict');
const {supportsModelRegistry, modelRegistryAvailable} = require('../src/sdk-capabilities');
test('model registry requires platform 3.0+ including daily and prerelease builds', () => {
  for (const version of ['3.0','3.0.0','3.0.0-pre2263','3.0.0~git20261020.abc-2264','3.1.0','4.0.0','10.0.0']) {
    assert.equal(supportsModelRegistry(`Platform Version = ${version}`),true,version);
  }
  for (const version of ['2.0.0','2.9.99','unknown','3','3.0junk','']) {
    assert.equal(supportsModelRegistry(`Platform Version = ${version}`),false,version);
  }
  assert.equal(supportsModelRegistry('SDK Version = 3.0.0_Palette_SDK_neat_develop_abc'),true);
  assert.equal(supportsModelRegistry('Platform Base = 2.0.0\nSDK Version = 3.0.0'),false);
  assert.equal(supportsModelRegistry('SDK Release = develop-abc'),false);
});
test('missing SDK metadata fails closed', async () => {
  assert.equal(await modelRegistryAvailable(async()=>{throw Error('missing');}),false);
  assert.equal(await modelRegistryAvailable(async(file)=>{assert.equal(file,'/etc/sdk-release');return 'Platform Base = 3.0.0';}),true);
});
test('unsupported SDK blocks direct command invocation before accessing CLI', async () => {
  let callback;let message;
  const vscode={commands:{registerCommand:(id,fn)=>{callback=fn;return {}; }},window:{showInformationMessage:m=>{message=m;}}};
  require('../src/model-registry').registerModels(vscode,{subscriptions:[]},()=>assert.fail('CLI must not run'));
  await callback();assert.match(message,/SDK 3.0/);
});
