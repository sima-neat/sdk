const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { execFileSync } = require('node:child_process');
const vm = require('node:vm');
const register = require('../tools/browser-trust/routes.cjs');

function app() {
  const routes = new Map();
  register({ get: (p, handler) => routes.set(p, handler) });
  return http.createServer((req, res) => {
    res.set = (name, value) => res.setHeader(name, value);
    res.status = code => { res.statusCode = code; return res; };
    res.json = data => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); };
    res.send = data => res.end(data);
    const handler = routes.get(new URL(req.url, 'http://localhost').pathname);
    if (req.method !== 'GET' || !handler) { res.statusCode = 404; res.end(); }
    else handler(req, res);
  });
}

test('real HTTP download is public, verified, noncached, and excludes keys', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'neat-ca-test-'));
  const old = process.env.CODE_SERVER_CERT;
  const oldHelp = process.env.SIMA_SDK_CERT_HELP;
  const openssl = args => execFileSync('openssl', args, { cwd: dir, stdio: 'ignore' });
  openssl(['req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','sima-sdk-rootCA.pem','-days','1','-subj','/CN=Test CA','-addext','basicConstraints=critical,CA:TRUE']);
  openssl(['req','-newkey','rsa:2048','-nodes','-keyout','leaf.key','-out','leaf.csr','-subj','/CN=localhost']);
  openssl(['x509','-req','-in','leaf.csr','-CA','sima-sdk-rootCA.pem','-CAkey','ca.key','-CAcreateserial','-out','neat-sdk.pem','-days','1']);
  process.env.CODE_SERVER_CERT = path.join(dir,'neat-sdk.pem');
  delete process.env.SIMA_SDK_CERT_HELP;
  const server = app();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const request = p => fetch(base + p);
  try {
    assert.equal((await (await request('/_neat/certificate-info')).json()).available, true);
    fs.appendFileSync(path.join(dir,'sima-sdk-rootCA.pem'), fs.readFileSync(path.join(dir,'ca.key')));
    const response = await request('/_neat/ca-certificate');
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.match(response.headers.get('content-disposition'), /attachment.*sima-sdk-rootCA.pem/);
    const pem = await response.text();
    assert.match(pem, /BEGIN CERTIFICATE/);
    assert.doesNotMatch(pem, /PRIVATE KEY/);
    assert.equal((await request('/_neat/ca.key')).status, 404);
    const worker = await request('/_neat/probe/service-worker.js');
    assert.match(worker.headers.get('content-type'), /javascript/);
    assert.equal(worker.headers.get('service-worker-allowed'), null);
    assert.doesNotMatch(await worker.text(), /clients.claim|fetch/);
    process.env.SIMA_SDK_CERT_HELP = 'off';
    assert.deepEqual(await (await request('/_neat/certificate-info')).json(), { available:false, enabled:false });
    assert.equal((await request('/_neat/ca-certificate')).status, 404);
    delete process.env.SIMA_SDK_CERT_HELP;
    openssl(['req','-x509','-newkey','rsa:2048','-nodes','-keyout','other.key','-out','sima-sdk-rootCA.pem','-days','1','-subj','/CN=Test CA','-addext','basicConstraints=critical,CA:TRUE']);
    assert.equal((await request('/_neat/ca-certificate')).status,404);
    fs.unlinkSync(path.join(dir,'sima-sdk-rootCA.pem'));
    assert.equal((await (await request('/_neat/certificate-info')).json()).available,false);
  } finally {
    await new Promise(resolve => server.close(resolve));
    if (old === undefined) delete process.env.CODE_SERVER_CERT; else process.env.CODE_SERVER_CERT=old;
    if (oldHelp === undefined) delete process.env.SIMA_SDK_CERT_HELP; else process.env.SIMA_SDK_CERT_HELP=oldHelp;
    fs.rmSync(dir, { recursive:true, force:true });
  }
});

function browser(registration, info=Promise.resolve({available:true,enabled:true})) {
  const elements = new Map();
  function el(id) {
    if (!elements.has(id)) elements.set(id, { hidden:true, open:false, value:'', events:{}, addEventListener(event, cb) { this.events[event]=cb; } });
    return elements.get(id);
  }
  const timers = new Map();
  const calls = [];
  const context = {
    document: { currentScript:{dataset:{base:'./'}}, getElementById:el, querySelectorAll:()=>[] },
    location:{href:'https://sdk.example.com/user/session/login'},
    navigator:{platform:'MacIntel',serviceWorker:{register:(url, options) => { calls.push({url,options});return registration; }}},
    window:{isSecureContext:true}, crypto:{randomUUID:()=> 'test'}, URL, AbortController,
    setTimeout: cb => { const id=timers.size+1;timers.set(id,cb);return id; }, clearTimeout:id=>timers.delete(id),
    fetch:async()=>({ok:true,json:()=>info}),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../tools/browser-trust/help.js'),'utf8'), context);
  return {el,timers,calls};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('success hides automatic hint, unregisters, and preserves manually opened help',async()=>{
  let resolve;let removed=0;
  const b=browser(new Promise(r=>resolve=r));
  b.el('neat-certificate-details').open=true;
  b.el('neat-certificate-details').events.toggle();
  resolve({unregister:async()=>{removed++;}});
  await flush();
  assert.equal(removed,1);
  assert.equal(b.el('neat-certificate-status').hidden,true);
  assert.equal(b.el('neat-certificate-details').open,true);
  assert.equal(b.calls[0].url,'https://sdk.example.com/user/session/_neat/probe/service-worker.js');
  assert.equal(b.calls[0].options.scope,'https://sdk.example.com/user/session/_neat/probe/check-test/');
  assert.equal(b.calls[0].options.updateViaCache,'none');
  assert.equal(b.el('neat-ca-download').href,'https://sdk.example.com/user/session/_neat/ca-certificate');
});
test('failure opens matching CA help without claiming a certificate error',async()=>{
  const b=browser(Promise.reject(new Error('policy denied')));
  await flush();
  assert.equal(b.el('neat-certificate-status').hidden,false);
  assert.match(b.el('neat-certificate-status').textContent,/Having trouble/);
  assert.equal(b.el('neat-certificate-details').open,true);
});
test('timeout is nonblocking and late success cleans up and hides hint',async()=>{
  let resolve;
  const b=browser(new Promise(r=>resolve=r));
  b.timers.get(1)();
  assert.equal(b.el('neat-certificate-status').hidden,false);
  resolve({unregister:async()=>true});
  await flush();
  assert.equal(b.el('neat-certificate-status').hidden,true);
});
test('ALB configuration hides local certificate help',async()=>{
  const b=browser(Promise.resolve({unregister:async()=>true}),Promise.resolve({available:false,enabled:false}));
  await flush();
  assert.equal(b.el('neat-certificate').hidden,true);
});

test('failure waits for matching CA metadata before opening help',async()=>{
  let resolveInfo;
  const b=browser(Promise.reject(new Error('denied')),new Promise(r=>resolveInfo=r));
  await flush();
  assert.equal(b.el('neat-certificate-details').open,false);
  resolveInfo({available:true,enabled:true});
  await flush();
  assert.equal(b.el('neat-certificate-details').open,true);
});
test('matching CA metadata arriving before failure also opens help',async()=>{
  let reject;
  const b=browser(new Promise((_,r)=>reject=r));
  await flush();
  assert.equal(b.el('neat-certificate-details').open,false);
  reject(new Error('denied'));
  await flush();
  assert.equal(b.el('neat-certificate-details').open,true);
});
test('failure without available enabled CA keeps help collapsed',async()=>{
  for (const info of [{available:false,enabled:true},{available:true,enabled:false}]) {
    const b=browser(Promise.reject(new Error('denied')),Promise.resolve(info));
    await flush();
    assert.equal(b.el('neat-certificate-details').open,false);
  }
});
test('failed metadata request keeps help collapsed on probe failure',async()=>{
  const b=browser(Promise.reject(new Error('denied')),Promise.resolve().then(()=>{throw new Error('offline');}));
  await flush();
  assert.equal(b.el('neat-certificate-details').open,false);
});
test('timeout keeps help collapsed even after late failure and matching metadata',async()=>{
  let reject,resolveInfo;
  const b=browser(new Promise((_,r)=>reject=r),new Promise(r=>resolveInfo=r));
  b.timers.get(1)();
  assert.equal(b.el('neat-certificate-details').open,false);
  reject(new Error('late failure'));
  resolveInfo({available:true,enabled:true});
  await flush();
  assert.equal(b.el('neat-certificate-details').open,false);
});
test('success leaves help collapsed with matching CA available',async()=>{
  const b=browser(Promise.resolve({unregister:async()=>true}));
  await flush();
  assert.equal(b.el('neat-certificate-details').open,false);
});
