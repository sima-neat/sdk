const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../scripts/sdk-code-server-cli.js'),'utf8');
async function run(args, available=true) {
 const calls=[], errors=[], process={argv:['node','wrapper',...args]};
 const ids={codex:'openai.chatgpt',claude:'anthropic.claude-code'};
 const components={codex:{id:ids.codex,version:'1.2.3'},claude:{id:ids.claude,version:'2.3.4'}};
 class Catalog {
  snapshot(){return {available,sdkVersion:'3.0.0',components,error:'Not qualified'};}
  async refresh(){return this.snapshot();}
  async artifact(key){return {file:'/verified/'+key+'.vsix',target:components[key]};}
 }
 const spawnSync=(file,argv)=>{
  calls.push(argv);
  if(argv.includes('--version'))return {status:0,stdout:'4.144.0 commit with Code 1.144.0'};
  if(argv.includes('--list-extensions'))return {status:0,stdout:'openai.chatgpt@1.2.3\nanthropic.claude-code@2.3.4\n'};
  return {status:0};
 };
 await vm.runInNewContext(source,{process,console:{error:x=>errors.push(x)},require:name=>{
  if(name==='node:child_process')return {spawnSync};
  if(name==='/usr/local/lib/sima-sdk/components.js')return {ComponentCatalog:Catalog,IDS:ids};
  return require(name);
 }});
 return {calls:JSON.parse(JSON.stringify(calls)),errors,code:process.exitCode};
}
test('ordinary code-server arguments retain the upstream contract',async()=>{
 const result=await run(['--bind-addr','0.0.0.0:9999','/workspace']);
 assert.deepEqual(result.calls,[['--bind-addr','0.0.0.0:9999','/workspace']]);
});
test('SDK setup agent requests become exact verified local VSIX installs',async()=>{
 const result=await run(['--extensions-dir','/test/extensions','--install-extension','openai.chatgpt']);
 assert.equal(result.code,undefined);
 assert.deepEqual(result.calls[1],['--extensions-dir','/test/extensions','--install-extension','/verified/codex.vsix','--force']);
 assert.deepEqual(result.calls[2],['--config','/dev/null','--extensions-dir','/test/extensions','--list-extensions','--show-versions']);
});
test('joined arguments and exact approved versions are supported',async()=>{
 const result=await run(['--install-extension=anthropic.claude-code@2.3.4','--extensions-dir=/test/extensions']);
 assert.equal(result.code,undefined);
 assert.deepEqual(result.calls[1],['--install-extension=/verified/claude.vsix','--extensions-dir=/test/extensions','--force']);
});
test('unqualified SDKs and explicitly incompatible versions never reach installation',async()=>{
 const blocked=await run(['--install-extension','openai.chatgpt'],false);
 assert.equal(blocked.code,1);assert.equal(blocked.calls.length,1);
 const mismatch=await run(['--install-extension','openai.chatgpt@9.9.9']);
 assert.equal(mismatch.code,1);assert.equal(mismatch.calls.length,1);
 assert.match(mismatch.errors[0],/not qualified/);
});
