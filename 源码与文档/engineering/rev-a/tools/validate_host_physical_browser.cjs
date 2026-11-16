// Real Chromium + real C controller + injected wire transport, no hardware.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/Users/linxiansheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),cp=require('child_process'),assert=require('assert'),crypto=require('crypto');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'aikey-wire-ui-'));
fs.mkdirSync(path.join(temp,'work'));fs.writeFileSync(path.join(temp,'work','fixture.txt'),'按钮颜色：灰色\n');
let server,browser,url,log='',failure;const checks=[],errors=[];
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const check=(name,value)=>{assert.ok(value,name);checks.push({name,status:'PASS'});console.log(name,'PASS');};
async function api(page,route,data={}){return page.evaluate(async({route,data})=>{
 const token=document.querySelector('meta[name="aikey-session"]').content;
 const response=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json','X-AIKEY-Session':token},body:JSON.stringify(data)});
 const body=await response.json();if(!response.ok)throw new Error(body.error);return body;
},{route,data});}
async function main(){
 server=cp.spawn('python3',[path.join(root,'tests/serve_physical_fixture.py'),path.join(temp,'work'),path.join(temp,'journal')],{cwd:root});
 server.stdout.on('data',d=>{log+=d;url=log.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];});server.stderr.on('data',d=>log+=d);
 for(let i=0;i<100&&!url;i++){if(server.exitCode!==null)throw new Error(log);await delay(50);}assert.ok(url);
 browser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
 const page=await browser.newPage({viewport:{width:1400,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.microphoneCalls=0;const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);navigator.mediaDevices.getUserMedia=(...a)=>{window.microphoneCalls++;return original(...a);};});
 await page.goto(url);await page.getByText('本地已连接 · USB',{exact:true}).waitFor();
 check('hardware mode hides simulated button controls',await page.locator('.controls').isHidden());
 await page.keyboard.down('F4');await delay(100);await page.keyboard.up('F4');await delay(100);
 check('keyboard simulation cannot inject hardware-mode input',await page.locator('#radial').isHidden());
 await api(page,'/api/test-fixture/buttons',{mask:8});await delay(100);await api(page,'/api/test-fixture/buttons',{mask:0});
 await page.locator('#radial').waitFor({state:'visible'});check('wire-delivered C button edges open radial',true);
 await page.getByRole('button',{name:'滚动',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#device-state').textContent.includes('HOST'));
 check('real firmware ACK admits special-mode ownership',true);
 await page.getByRole('button',{name:'取消 / R',exact:true}).click();await delay(100);
 await api(page,'/api/test-fixture/buttons',{mask:4});
 await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('未找到唯一 AI KEY 麦克风'));
 await page.waitForFunction(()=>document.querySelector('#device-state').textContent.includes('mic: off'));
 check('missing USB microphone fails closed without capturing computer microphone',await page.evaluate(()=>window.microphoneCalls===0));
 await api(page,'/api/test-fixture/buttons',{mask:0});await delay(100);await page.getByRole('button',{name:'取消 / R',exact:true}).click();
 await delay(100);await api(page,'/api/test-fixture/buttons',{mask:8});await delay(100);await api(page,'/api/test-fixture/buttons',{mask:0});
 await page.locator('#radial').waitFor({state:'visible'});check('cancel reconnect admits fresh input without replay loop',true);
 check('fixture remains explicitly nonphysical in status',(await api(page,'/api/status')).physical_device===false);
 check('no browser script errors',errors.length===0);
 await page.screenshot({path:path.join(root,'reports/host-wire-fixture-browser.png'),fullPage:true});
}
(async()=>{try{await main();}catch(e){failure=e.stack;console.error(failure);}finally{
 if(browser)await browser.close();if(server){server.kill('SIGINT');await delay(500);if(server.exitCode===null)server.kill('SIGTERM');}
 const files=['host/physical_device.py','host/transports.py','host/server.py','host/web/app.js','host/web/recorder.js','tests/serve_physical_fixture.py','tests/host_physical_test.py'];
 fs.writeFileSync(path.join(root,'reports/host-physical-browser.json'),JSON.stringify({status:failure?'FAIL':'PASS',scope:'Real Chromium and C firmware over an injected wire boundary; USB mode UI; no physical USB/BLE or microphone',checks,errors,failure,source_sha256:Object.fromEntries(files.map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex')]))},null,2)+'\n');
 fs.writeFileSync(path.join(root,'reports/host-physical-browser-server.log'),log);fs.rmSync(temp,{recursive:true,force:true});if(failure)process.exitCode=1;
}})();
