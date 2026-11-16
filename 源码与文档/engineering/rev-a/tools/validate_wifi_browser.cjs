// Native C control and audio framing, real TLS, real local ASR/model and files.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/Users/linxiansheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),os=require('os'),cp=require('child_process'),assert=require('assert'),crypto=require('crypto');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'aikey-wifi-ui-')),work=path.join(temp,'work');fs.mkdirSync(work);
const target=path.join(work,'fixture.txt'),original='按钮颜色：灰色\n按钮宽度：120 像素\n';fs.writeFileSync(target,original);
const fixtureDir=path.join(os.homedir(),'.cache/ai-key-rev-a/fixtures');fs.mkdirSync(fixtureDir,{recursive:true});fs.copyFileSync(path.join(root,'tests/fixtures/voice-change-color.wav'),path.join(fixtureDir,'voice-change-color.wav'));
let server,browser,url,log='',failure;const checks=[],errors=[];const delay=ms=>new Promise(r=>setTimeout(r,ms));
const check=(name,value)=>{assert.ok(value,name);checks.push({name,status:'PASS'});console.log(name,'PASS');};
async function api(page,route,data={}){return page.evaluate(async({route,data})=>{const token=document.querySelector('meta[name="aikey-session"]').content;const r=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json','X-AIKEY-Session':token},body:JSON.stringify(data)});const b=await r.json();if(!r.ok)throw new Error(b.error);return b;},{route,data});}
async function main(){
 server=cp.spawn('/opt/homebrew/bin/python3.14',[path.join(root,'tests/serve_wifi_fixture.py'),work,path.join(temp,'journal')],{cwd:root});
 server.stdout.on('data',d=>{log+=d;url=log.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];});server.stderr.on('data',d=>log+=d);
 for(let i=0;i<600&&!url;i++){if(server.exitCode!==null)throw new Error(log);await delay(50);}assert.ok(url);
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1400,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.microphoneCalls=0;navigator.mediaDevices.getUserMedia=async()=>{window.microphoneCalls++;throw new Error('Browser microphone forbidden in wireless test');};});
 await page.goto(url);await page.getByText('本地已连接 · BLE',{exact:true}).waitFor();
 for(let i=0;i<50;i++){if((await api(page,'/api/status')).wifi_audio.ready)break;await delay(50);}
 check('authenticated TLS audio connected to current C session',(await api(page,'/api/status')).wifi_audio.ready);
 check('no samples before held trigger',(await api(page,'/api/test-fixture/audio')).sent_frames===0);
 await api(page,'/api/test-fixture/buttons',{mask:4});await page.getByText('正在录音 · 松开结束',{exact:true}).waitFor({timeout:5000});for(let i=0;i<150;i++){const sent=await api(page,'/api/test-fixture/audio');if(sent.sent_frames>=sent.source_frames+10)break;await delay(100);}
 const during=await api(page,'/api/test-fixture/audio');console.log('Audio frame counts',during);check('held trigger routes C-framed synthesized PCM over real TLS',during.sent_frames>=during.source_frames&&during.streams===1);
 await api(page,'/api/test-fixture/buttons',{mask:0});await page.waitForFunction(()=>document.querySelector('#device-state').textContent.includes('mic: off'));
 await delay(150);const stopped=(await api(page,'/api/test-fixture/audio')).sent_frames;await delay(150);check('trigger release stops new PCM frames',(await api(page,'/api/test-fixture/audio')).sent_frames===stopped);
 await page.waitForFunction(()=>document.querySelector('#instruction').value.includes('灰色'),{},{timeout:180000});check('TLS WAV reaches real whisper editable preview',!(await page.locator('#instruction').isDisabled()));
 check('wireless voice never opens browser microphone',await page.evaluate(()=>window.microphoneCalls===0));
 check('transcription leaves file unchanged',fs.readFileSync(target,'utf8')===original);
 await page.getByRole('button',{name:'确认发送',exact:false}).click();await page.locator('#comparison').waitFor({state:'visible',timeout:180000});check('real Qwen proposal still requires apply',fs.readFileSync(target,'utf8')===original);
 await page.getByRole('button',{name:'确认应用到文件',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#comparison').hidden);
 check('confirmed wireless instruction changes actual file',fs.readFileSync(target,'utf8')===original.replace('灰色','蓝色'));
 await page.getByRole('button',{name:'撤销本次应用',exact:true}).click();await page.getByText('已撤销并读回原文').waitFor();check('undo restores exact original bytes',fs.readFileSync(target,'utf8')===original);
 check('no browser errors',errors.length===0);await page.screenshot({path:path.join(root,'reports/host-wifi-loopback-browser.png'),fullPage:true});
}
(async()=>{try{await main();}catch(e){failure=e.stack;console.error(failure);if(browser){const p=browser.contexts()[0]?.pages()[0];if(p)console.error(await p.locator('#notice').textContent(),await p.locator('#device-state').textContent());}}finally{
 if(browser)await browser.close();if(server){server.kill('SIGINT');await delay(500);if(server.exitCode===null)server.kill('SIGTERM');}
 const files=['host/wifi_audio.py','host/server.py','host/physical_device.py','host/web/app.js','host/web/recorder.js','tests/serve_wifi_fixture.py','firmware/core/audio_wire.c','firmware/core/controller.c'];
 fs.writeFileSync(path.join(root,'reports/wifi-browser-validation.json'),JSON.stringify({status:failure?'FAIL':'PASS',scope:'Real Chromium, C controller/frame codec, PSK TLS loopback, synthesized WAV, real local whisper/Qwen and temporary-file apply/readback/undo; no physical BLE, Wi-Fi or PDM',checks,errors,failure,source_sha256:Object.fromEntries(files.map(f=>[f,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex')]))},null,2)+'\n');
 fs.writeFileSync(path.join(root,'reports/wifi-browser-server.log'),log);fs.rmSync(temp,{recursive:true,force:true});if(failure)process.exitCode=1;
}})();
