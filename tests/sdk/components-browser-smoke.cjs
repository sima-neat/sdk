// Run against a fresh, disposable SDK container. Never supply customer profiles.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const manifest = require('../../components.json');
const directory = process.env.QUALIFICATION_OUTPUT || '/tmp/sdk-component-qualification';
fs.mkdirSync(directory, {recursive:true});
const report = {status:'running', authenticated_agent_use:false, checks:[]};
const container = process.env.SDK_CONTAINER_NAME;
const user = process.env.SDK_CONTAINER_USER || 'sdk-test';
function docker(...args) { return execFileSync('docker', args, {encoding:'utf8',timeout:30000}).trim(); }
function execute(code) { return docker('exec','-u',user,container,'python3','-c',code); }
async function main() {
  if (!container || !process.env.SDK_TEST_URL || !process.env.SDK_TEST_PASSWORD_FILE)
    throw Error('SDK_CONTAINER_NAME, SDK_TEST_URL and SDK_TEST_PASSWORD_FILE are required');
  report.sdk_image_digest = docker('inspect',container,'--format','{{.Image}}');
  report.architecture = docker('image','inspect',report.sdk_image_digest,'--format','{{.Architecture}}');
  report.codex_cli_version = docker('exec',container,'codex','--version');
  report.components_manifest_sha256 = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(__dirname,'../../components.json'))).digest('hex');
  report.server = docker('exec',container,'/opt/code-server/bin/code-server','--config','/dev/null','--version');
  const row = manifest.sdks[process.env.SDK_TEST_VERSION || manifest.build_sdk_version];
  const browser = await chromium.launch({channel:process.env.CHROME_CHANNEL || 'chrome',headless:true});
  report.browser = 'Chrome ' + browser.version();
  const page = await browser.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  async function landing() {
    const deadline = Date.now()+90000;
    while (Date.now()<deadline) {
      for (const frame of page.frames()) {
        try { if (await frame.locator('[data-agent="codex"] .install-agent').count()) return frame; } catch {}
      }
      await new Promise(resolve=>setTimeout(resolve,500));
    }
    throw Error('Palette landing page did not become available');
  }
  try {
    await page.goto(process.env.SDK_TEST_URL,{waitUntil:'domcontentloaded',timeout:60000});
    if (page.url().includes('/login')) {
      await page.locator('input[name=password]').fill(fs.readFileSync(process.env.SDK_TEST_PASSWORD_FILE,'utf8').trim());
      await page.locator('button[type=submit], input[type=submit]').click();
    }
    console.log('Code-server login completed');
    for (const key of ['codex','claude']) {
      console.log(`Checking ${key} installation`);
      let frame=await landing();
      console.log("Palette frame located");
      await frame.locator("#tab-agents").click();
      const card=frame.locator(`[data-agent="${key}"]`);
      await card.locator('.install-agent').waitFor();
      await page.waitForFunction(()=>true); // Establish responsiveness before download.
      const deadline=Date.now()+600000;
      console.log("Policy status: "+await card.locator(".agent-progress").textContent());
      while (await card.locator('.install-agent').isDisabled()) {
        const message=await card.locator(".agent-progress").textContent();
        if(message && !message.includes("Checking")) throw Error(message);
        if(Date.now()>deadline)throw Error('No compatible candidate mapping became available');
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      if((await card.locator('.install-agent').textContent()).includes('Install'))await card.locator('.install-agent').click();
      console.log(`${key}: install dispatched`);
      while(Date.now()<deadline) {
        for(const name of [/Trust Publisher.*Install/i,/Install Anyway/i]) {
          const trust=page.getByRole('button',{name});
          if(await trust.count())await trust.first().click();
        }
        const status=await card.locator('.install-status').textContent();
        if(status.includes('Reload needed')) {await page.reload({waitUntil:'domcontentloaded'});frame=await landing();break;}
        if(status.includes('Installed'))break;
        const error=await card.locator('.agent-progress').textContent();
        if(error.includes('Installation did not finish'))throw Error(`${key}: installation failed`);
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      frame=await landing();
      await frame.locator("#tab-agents").click();
      const current=frame.locator(`[data-agent="${key}"]`);
      let status='';
      for(let attempt=0;attempt<120;attempt++) {
        status=await current.locator('.install-status').textContent();
        if(status.includes(row.components[key].version) && !(await current.locator('.install-agent').isDisabled()))break;
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      if(!status.includes(row.components[key].version))throw Error(`${key}: wrong selected version`);
      await current.locator('.install-agent').filter({hasText:'Open'}).click({timeout:60000});
      await Promise.race([page.evaluate(()=>1+1),new Promise((_,reject)=>setTimeout(()=>reject(Error('Editor renderer froze after agent activation')),15000))]);
      let ready=false;
      for(let attempt=0;attempt<120;attempt++) {
        await Promise.race([page.evaluate(()=>1+1),new Promise((_,reject)=>setTimeout(()=>reject(Error('Editor renderer froze during agent startup')),15000))]);
        for(const candidate of page.frames()) {
          try {
            if(candidate===page.mainFrame() || candidate===frame)continue;
            const text=await candidate.locator('body').innerText({timeout:1000});
            const provider=key==='codex'?/Codex|ChatGPT/i:/Claude/i;
            if(provider.test(text) && /Sign in|Log in|API key|Connect (?:your )?account/i.test(text))ready=true;
          } catch {}
        }
        if(ready)break;
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      if(!ready)throw Error(`${key}: agent interface did not reach its account setup view`);
      report.checks.push(`${key}: exact install, reload, account setup UI and responsive startup`);
    }
    execute('from pathlib import Path; Path("/workspace/component-smoke.txt").write_text("component smoke\\n")');
    const modifier=process.platform==='darwin'?'Meta':'Control';
    await page.keyboard.press(`${modifier}+p`);await page.locator('.quick-input-widget input').first().fill('component-smoke.txt');
    await page.locator('.quick-input-list .monaco-list-row').filter({hasText:'component-smoke.txt'}).first().click({timeout:15000});
    await page.locator('.monaco-editor .view-lines').last().click({position:{x:30,y:10},timeout:15000});
    await page.keyboard.press(`${modifier}+End`);await page.keyboard.type('saved by browser smoke');await page.keyboard.press(`${modifier}+s`);
    await new Promise(resolve=>setTimeout(resolve,1000));
    if(!execute('from pathlib import Path; print(Path("/workspace/component-smoke.txt").read_text())').includes('saved by browser smoke'))throw Error('Editor save did not reach workspace');
    await page.keyboard.press('F1');await page.locator('.quick-input-widget input').first().fill('>Terminal: Create New Terminal');
    await page.locator('.quick-input-list .monaco-list-row').filter({hasText:'Create New Terminal'}).first().click({timeout:15000});
    await page.locator('.terminal-wrapper').first().waitFor({timeout:15000});
    await page.reload({waitUntil:'domcontentloaded'});await landing();
    report.checks.push('workspace edit/save, terminal creation, browser reload/reconnect');
    docker('exec',container,'supervisorctl','restart','code-server');
    let connected=false;
    for(let attempt=0;attempt<30;attempt++) {
      try { await page.goto(process.env.SDK_TEST_URL,{waitUntil:'domcontentloaded',timeout:10000});connected=true;break; }
      catch { await new Promise(resolve=>setTimeout(resolve,500)); }
    }
    if(!connected)throw Error('Workbench did not recover after service restart');
    if(page.url().includes('/login')) {
      await page.locator('input[name=password]').fill(fs.readFileSync(process.env.SDK_TEST_PASSWORD_FILE,'utf8').trim());
      await page.locator('button[type=submit], input[type=submit]').click();
    }
    await landing();await page.evaluate(()=>1+1);
    report.checks.push('code-server service restart and workbench recovery');
    report.installed=JSON.parse(execute('import json,pathlib; p=pathlib.Path.home()/".local/share/code-server/extensions/extensions.json"; print(json.dumps([{ "id":x["identifier"]["id"], "version":x["version"], "metadata":x.get("metadata",{}) } for x in json.loads(p.read_text()) if x["identifier"]["id"].lower() in ("openai.chatgpt","anthropic.claude-code")]))'));
    for(const [key,item] of Object.entries(row.components)) {
      if(key==='codex-cli')continue;
      const installed=report.installed.find(x=>x.id.toLowerCase()===item.id);
      if(installed?.version!==item.version || installed.metadata.pinned!==true)throw Error(`${key}: installed version/update pin not retained`);
    }
    report.status='passed';report.console_errors=errors;
    await page.screenshot({path:path.join(directory,'workbench.png')});
  } catch (error) {
    await page.screenshot({path:path.join(directory,"failure.png"),timeout:5000}).catch(()=>{});
    throw error;
  } finally { await browser.close(); }
}
main().catch(error=>{report.status='failed';report.error=error.message;process.exitCode=1;}).finally(()=>{
 fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify(report,null,2));
});
