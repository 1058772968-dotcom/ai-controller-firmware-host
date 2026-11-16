import {Interaction,boxFromPoints} from './interaction.js';
import {HeldRecorder,NetworkRecorder,base64} from './recorder.js';
const $=id=>document.getElementById(id),token=document.querySelector('meta[name="aikey-session"]').content;
const labels={pointer:'普通鼠标',radial:'快捷圆盘',scroll:'倾斜滚动',page:'拨动翻页',zoom:'缩放',pan:'平移',mark:'标注',draw:'圈画中',voice:'正在录音',review:'检查要求',sending:'本地推理中',compare:'修改对比'};
let recorder=new HeldRecorder();let context=null,proposal=null,receipt=null,epoch=0,lockPromise=null,pendingAudio=null;
let deviceMode='disconnected',physicalDevice=false,lastSession=null;
let cursor=null,rawMask=0,previousButtons=0,pulseBusy=false,deviceReady=false,inputReady=false,owner=0,claimPromise=null,ready=false;
let offset=performance.now(),documentText='',documentHash=null,zoom=1,selectedMode='scroll',drawPoints=[],regions=[],arrows=[],dragging=null,pointer={x:0,y:0};
let inference=false,changing=false,autoStopped=false,buttonQueue=Promise.resolve(),drawTool='region',laserTimer=null,drawStartPromise=null,drawEndPromise=null;
const interaction=new Interaction(event=>{Promise.resolve(handle(event)).catch(error=>notify(error.message,true));});
async function api(path,data={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-AIKEY-Session':token},body:JSON.stringify(data)});const body=await response.json();if(!response.ok)throw new Error(body.error||'本地服务请求失败');return body;}
function notify(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
function phase(title,help){$('phase-title').textContent=title;$('phase-help').textContent=help;}
function updateButtons(){$('send').disabled=!context||context.sent||!$('instruction').value.trim()||inference;$('apply').disabled=!proposal||changing;$('undo').disabled=!receipt||changing;$('adapter').disabled=inference||Boolean(proposal);}
function renderDocument(){
  $('document').replaceChildren();documentText.split('\n').forEach((text,index)=>{const line=document.createElement('span');line.className='line';line.dataset.number=index+1;line.textContent=text||' ';$('document').append(line);});
  $('surface').style.transform=`scale(${zoom})`;updateView();drawMarks();
}
function updateView(){const v=$('viewport');$('view-info').textContent=`${Math.round(zoom*100)}% · 第 ${Math.floor(v.scrollTop/Math.max(1,v.clientHeight))+1} 页`;}
async function readFile(){const path=$('files').value;if(!path)return;const result=await api('/api/read',{path});if(path!==$('files').value)return;documentText=result.text;documentHash=result.sha256;$('file-name').textContent=path;renderDocument();}
async function lockTarget(){
  const generation=++epoch;context=null;proposal=null;pendingAudio=null;$('comparison').hidden=true;$('instruction').value='';$('instruction').disabled=true;updateButtons();
  if(!receipt)$('receipt').hidden=true;else $('receipt').querySelector('.eyebrow').textContent='上一笔操作 / 已核对';
  const path=$('files').value,snapshot=regions.map(x=>({...x})),surface=$('surface').getBoundingClientRect();
  const selected_lines=[...$('document').children].filter(line=>{const b=line.getBoundingClientRect(),x=(b.left-surface.left)/zoom,y=(b.top-surface.top)/zoom;return snapshot.some(r=>x<r.x+r.w&&x+b.width/zoom>r.x&&y<r.y+r.h&&y+b.height/zoom>r.y);}).map(line=>Number(line.dataset.number));
  const annotations={regions:snapshot,arrows:arrows.map(a=>({x1:a.from.x,y1:a.from.y,x2:a.to.x,y2:a.to.y})),selected_lines};
  const request=api('/api/lock',{path,annotations,expected_sha256:documentHash}).then(result=>{
    if(generation!==epoch)throw new Error('目标锁定已取消');context=result;context.regions=snapshot;
    $('locked-path').textContent=result.path;$('locked-hash').textContent='SHA256 '+result.sha256.slice(0,16)+'…'+(selected_lines.length?` · ${selected_lines.length} 行标注文本`:'');$('target-label').textContent='已锁定 '+result.path;
    $('instruction').disabled=false;updateButtons();return result;
  });lockPromise=request;return request;
}
async function claim(){
  if(owner===1){ready=true;return;}
  if(!deviceReady)throw new Error('设备尚未连接');
  if(!claimPromise){const generation=epoch;claimPromise=api('/api/device/command',{command:2}).then(state=>{owner=state.owner;if(generation!==epoch)throw new Error('模式进入已取消');if(owner!==1)throw new Error('固件未确认增强模式');ready=true;}).finally(()=>{claimPromise=null;});}
  await claimPromise;
}
async function release(){ready=false;hardwareCursor.hidden=true;if(deviceReady)try{await api('/api/device/command',{command:4});owner=0;}catch(error){notify(error.message,true);}}
async function command(type,value=0){return api('/api/device/command',{command:type,value});}
async function cancel(reason='操作已取消'){
  ++epoch;recorder.cancel();pendingAudio=null;rawMask=0;context=null;proposal=null;lockPromise=null;ready=false;owner=0;inputReady=false;
  interaction.held.clear();interaction.blocked.clear();interaction.lastVoice=-Infinity;interaction.enter('pointer');
  $('comparison').hidden=true;$('instruction').disabled=true;document.querySelectorAll('[data-key]').forEach(b=>b.classList.remove('held'));updateButtons();
  await buttonQueue.catch(()=>{});await api('/api/cancel');
  if(deviceReady&&!document.hidden){const result=await api('/api/device/connect');cursor=result.cursor;previousButtons=result.state.buttons;owner=result.state.owner;lastSession=result.state.session;inputReady=true;}
  phase('准备好，再按住 V','按下时锁定文件。松开后检查文字，确认发送才生成提案。');notify(reason);
}
async function recognize(buffer){
  const generation=epoch,c=context;if(!c||!buffer)throw new Error('录音太短，或麦克风权限尚未就绪。请重新按住 V。');
  inference=true;updateButtons();phase('正在识别本地录音','松开后麦克风已关闭，音频只交给本机 whisper。');
  try{const result=await api('/api/asr',{context_id:c.id,wav_base64:base64(buffer)});if(generation!==epoch)return;
    $('instruction').value=result.text;$('asr-info').textContent=`本地识别 · ${result.duration_s.toFixed(1)} 秒录音 · ${result.elapsed_s.toFixed(1)} 秒处理`;
    phase('检查文字，再确认发送','可以先修正转写。当前文件尚未修改。');notify('语音识别完成，请检查可编辑预览。');
  }finally{inference=false;updateButtons();}
}
function point(event){const rect=$('surface').getBoundingClientRect();return {x:(event.clientX-rect.left)/zoom,y:(event.clientY-rect.top)/zoom};}
function drawMarks(){
  const svg=$('marks');svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${$('surface').clientWidth} ${$('surface').scrollHeight}`);
  const add=(name,attrs)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);svg.append(e);return e;};
  regions.forEach((r,index)=>{add('rect',{x:r.x,y:r.y,width:r.w,height:r.h,rx:3,fill:'#608e7730',stroke:'#47715a','stroke-width':1.5});const t=add('text',{x:r.x+5,y:r.y+14,fill:'#355640','font-size':10});t.textContent=index+1;
    for(const [cx,cy]of [[r.x,r.y],[r.x+r.w,r.y],[r.x,r.y+r.h],[r.x+r.w,r.y+r.h]])add('circle',{cx,cy,r:3,fill:'#f7f7ed',stroke:'#47715a'});});
  for(const a of arrows){add('line',{x1:a.from.x,y1:a.from.y,x2:a.to.x,y2:a.to.y,stroke:'#997347','stroke-width':2});const angle=Math.atan2(a.to.y-a.from.y,a.to.x-a.from.x);const pts=[a.to,{x:a.to.x-10*Math.cos(angle-.45),y:a.to.y-10*Math.sin(angle-.45)},{x:a.to.x-10*Math.cos(angle+.45),y:a.to.y-10*Math.sin(angle+.45)}];add('polygon',{points:pts.map(p=>`${p.x},${p.y}`).join(' '),fill:'#997347'});}
  if(drawPoints.length)add('polyline',{points:drawPoints.map(p=>`${p.x},${p.y}`).join(' '),fill:'none',stroke:'#50745b','stroke-width':2});
}
function choose(){if(!ready)return;if(selectedMode==='ai'){interaction.enter('review');lockTarget().then(()=>{$('instruction').focus();phase('输入要求，确认后发送','当前目标已锁定。');}).catch(e=>notify(e.message,true));}else if(selectedMode==='mark'){interaction.arm(drawTool);}else interaction.enter(selectedMode);}
function compare(which){if(!proposal)return;for(const id of ['before','after','diff'])$(id+'-tab').setAttribute('aria-pressed',String(id===which));$('comparison-text').textContent=which==='before'?proposal.before_text:which==='diff'?proposal.diff:proposal.new_text;}
async function handle(event){
  if(event.type==='mode'){
    $('mode-label').textContent=labels[event.mode]||event.mode;$('radial').hidden=event.mode!=='radial';$('motion-zone').hidden=deviceMode!=='native-core-simulation'||!['scroll','zoom','page','compare'].includes(event.mode);
    $('mark-tools').hidden=!['mark','draw'].includes(event.mode);
    if(event.mode==='pointer'){if(drawEndPromise)await drawEndPromise.catch(()=>{});await release();}else if(!['voice','review','sending','compare'].includes(event.mode))await claim();
  }else if(event.type==='voice-arm'){
    if(inference||changing)throw new Error('请先等待当前处理结束');await lockTarget();phase('目标已锁定','继续按住开始录音，松开检查。');
  }else if(event.type==='voice-start'){
    const generation=epoch;await lockPromise;if(generation!==epoch||!(rawMask&4))return;
    await claim();if(generation!==epoch||!(rawMask&4))return;await command(5,1);if(generation!==epoch||!(rawMask&4)){await command(5,0);return;}
    let started=false;try{started=await recorder.start(()=>{autoStopped=true;rawMask&=~4;if(deviceMode==='native-core-simulation')api('/api/device/buttons',{mask:rawMask});command(5,0);notify('已达到 60 秒上限，录音已取消。请缩短后重录。',true);},deviceMode==='usb'?/AI KEY|Held-key microphone/i:null);}catch(error){recorder.cancel();await command(5,0).catch(()=>{});throw error;}
    if(started&&generation===epoch){phase('正在录音 · 松开结束','录音不会自动发送，也不会修改文件。');notify('正在录音。');}
  }else if(event.type==='voice-preview'){
    await command(5,0);const audio=await (pendingAudio||recorder.stop());pendingAudio=null;
    if(autoStopped){autoStopped=false;return;}await lockPromise;await recognize(audio);
  }else if(event.type==='voice-disarm'){
    recorder.cancel();notify('短按未录音；连续双击 V 可重新居中。');
  }else if(event.type==='recenter'){await command(8);notify('已发送中立姿态重设命令；实际 IMU 仍需样机验证。');
  }else if(event.type==='draw-start'){clearTimeout(laserTimer);drawPoints=[event.point||pointer];drawMarks();drawStartPromise=(async()=>{await claim();await command(6,1);})();await drawStartPromise;
  }else if(event.type==='draw-point'){if(drawStartPromise){drawPoints.push(event.point);drawMarks();}
  }else if(event.type==='draw-end'){
    const points=[...drawPoints],tool=drawTool,generation=epoch;
    drawEndPromise=(async()=>{await drawStartPromise;await command(6,0);if(generation!==epoch)return;
      if(tool==='laser'){laserTimer=setTimeout(()=>{drawPoints=[];drawMarks();},850);notify('临时轨迹将在 850 毫秒后消失，不加入请求。');}
      else if(tool==='arrow'){if(points.length>1)arrows.push({from:points[0],to:points.at(-1)});drawPoints=[];drawMarks();notify(points.length>1?'已保留关系箭头。':'轨迹太短，未创建箭头。');}
      else{const rect=boxFromPoints(points,$('surface').clientWidth,$('surface').scrollHeight);if(rect)regions.push(rect);drawPoints=[];drawMarks();notify(rect?'已保留标注区域，可继续圈画或按 V。':'标注范围太小，未创建选区。');}
    })();try{await drawEndPromise;}finally{drawEndPromise=null;drawStartPromise=null;}
  }else if(event.type==='choose')choose();
  else if(event.type==='scroll'&&ready){$('viewport').scrollTop+=event.delta;updateView();}
  else if(event.type==='zoom'&&ready){zoom=Math.max(.7,Math.min(2.2,zoom+event.delta));$('surface').style.transform=`scale(${zoom})`;updateView();}
  else if(event.type==='page-preview'){notify(event.direction?`松开 S 后${event.direction>0?'下一屏':'上一屏'}`:'保持 S 并左右移动，松开执行一次。');}
  else if(event.type==='page-commit'&&ready){$('viewport').scrollTop+=event.direction*$('viewport').clientHeight;updateView();}
  else if(event.type==='pan'&&ready){$('viewport').scrollLeft-=event.dx;$('viewport').scrollTop-=event.dy;updateView();}
  else if(event.type==='compare')compare(event.after?'after':'before');
  else if(event.type==='cancel')await cancel(event.reason);
  else if(event.type==='mouse'&&deviceMode==='native-core-simulation')notify(`普通鼠标 ${event.button==='left'?'左':'右'}键${event.edge==='down'?'按下':'松开'}（电脑端模拟，不向系统注入）`);
  else if(event.type==='ui-click'&&ready){const target=document.elementFromPoint(pointer.clientX||0,pointer.clientY||0);if(target&&target.matches('#send,#apply,#undo,#cancel'))target.click();}
}
async function button(key,down){
  if(deviceMode!=='native-core-simulation'||!deviceReady||!inputReady)return;const bit={L:1,R:2,V:4,S:8}[key];if(Boolean(rawMask&bit)===down)return;rawMask=down?rawMask|bit:rawMask&~bit;
  document.querySelectorAll(`[data-key="${key}"]`).forEach(b=>b.classList.toggle('held',down));
  if(key==='V'&&!down)pendingAudio=recorder.stop();
  const mask=rawMask;buttonQueue=buttonQueue.catch(()=>{}).then(()=>api('/api/device/buttons',{mask}));await buttonQueue;
}
async function pulse(){
  if(pulseBusy||document.hidden||!deviceReady)return;pulseBusy=true;const generation=epoch;
  try{const result=await api('/api/device/pulse',{cursor});if(generation!==epoch)return;cursor=result.cursor;owner=result.state.owner;inputReady=true;offset=performance.now()-result.state.time_ms;
    $('device-state').textContent=`owner: ${owner?'HOST':'POINTER'} · buttons: ${result.state.buttons}\nmic: ${result.state.flags&2?'on':'off'} · firmware session: ${result.state.session}\nphysical device: ${result.physical_device}`;
    if(lastSession!==null&&lastSession!==result.state.session){lastSession=result.state.session;await cancel('设备会话改变，本轮操作已取消。');return;}lastSession=result.state.session;
    for(const event of result.events){if(event.type===0x81){hardwareMotion(event.dx,event.dy);continue;}if(event.type===6){previousButtons=0;rawMask=0;recorder.cancel();interaction.held.clear();continue;}if(event.type!==1)continue;const changed=previousButtons^event.buttons;previousButtons=event.buttons;
      if(deviceMode!=='native-core-simulation'){rawMask=event.buttons;if((changed&4)&&!(rawMask&4))pendingAudio=recorder.stop();}
      for(const [key,bit]of [['L',1],['R',2],['V',4],['S',8]])if(changed&bit){if(event.buttons&bit)interaction.down(key,event.time_ms);else interaction.up(key,event.time_ms);}}
  }catch(error){deviceReady=false;recorder.cancel();interaction.disconnect();notify(error.message,true);}finally{pulseBusy=false;}
}
const hardwareCursor=document.createElement('div');hardwareCursor.className='hardware-cursor';hardwareCursor.hidden=true;hardwareCursor.setAttribute('aria-hidden','true');document.body.append(hardwareCursor);
function hardwareMotion(dx,dy){
  if(deviceMode==='native-core-simulation'||owner!==1)return;
  const viewport=$('viewport').getBoundingClientRect(),surface=$('surface').getBoundingClientRect();
  const x=Math.max(0,Math.min(innerWidth,(pointer.clientX??(viewport.left+viewport.width/2))+dx));
  const y=Math.max(0,Math.min(innerHeight,(pointer.clientY??(viewport.top+viewport.height/2))+dy));
  pointer={x:(x-surface.left)/zoom,y:(y-surface.top)/zoom,clientX:x,clientY:y};
  hardwareCursor.hidden=false;hardwareCursor.style.left=x+'px';hardwareCursor.style.top=y+'px';
  interaction.move(interaction.mode==='pan'?{x,y}:pointer);
  interaction.tilt(interaction.angle.x+dx/8,interaction.angle.y+dy/8);
  const target=document.elementFromPoint(x,y)?.closest('[data-mode]');
  if(target){selectedMode=target.dataset.mode;for(const b of $('radial-options').children)b.classList.toggle('selected',b===target);}
}
let lastFrame=performance.now();function frame(now){interaction.tick(now-offset,Math.min(.05,(now-lastFrame)/1000));lastFrame=now;requestAnimationFrame(frame);}requestAnimationFrame(frame);
for(const buttonElement of document.querySelectorAll('[data-key]')){
  buttonElement.addEventListener('pointerdown',event=>{event.preventDefault();buttonElement.setPointerCapture(event.pointerId);button(buttonElement.dataset.key,true).catch(e=>notify(e.message,true));});
  for(const name of ['pointerup','pointercancel','lostpointercapture'])buttonElement.addEventListener(name,()=>button(buttonElement.dataset.key,false).catch(e=>notify(e.message,true)));
}
document.addEventListener('keydown',event=>{const key={F1:'L',F2:'R',F3:'V',F4:'S'}[event.key];if(key&&!event.repeat){event.preventDefault();button(key,true).catch(e=>notify(e.message,true));}if(event.key==='Escape')cancel().catch(e=>notify(e.message,true));});
document.addEventListener('keyup',event=>{const key={F1:'L',F2:'R',F3:'V',F4:'S'}[event.key];if(key){event.preventDefault();button(key,false).catch(e=>notify(e.message,true));}});
$('viewport').addEventListener('pointermove',event=>{pointer={...point(event),clientX:event.clientX,clientY:event.clientY};interaction.move(interaction.mode==='pan'?{x:event.clientX,y:event.clientY}:point(event));if(dragging){const r=regions[dragging.index],p=point(event),o=dragging.original;if(dragging.corner%2===0){r.x=Math.max(0,Math.min(p.x,o.x+o.w-14));r.w=o.x+o.w-r.x;}else r.w=Math.max(14,p.x-o.x);if(dragging.corner<2){r.y=Math.max(0,Math.min(p.y,o.y+o.h-14));r.h=o.y+o.h-r.y;}else r.h=Math.max(14,p.y-o.y);drawMarks();}});
$('viewport').addEventListener('pointerdown',event=>{if(['mark','pan'].includes(interaction.mode)&&ready){interaction.down('L',performance.now()-offset);$('viewport').setPointerCapture(event.pointerId);event.preventDefault();}else if(interaction.mode==='pointer'){const p=point(event);for(let index=0;index<regions.length;index++){const r=regions[index],corners=[[r.x,r.y],[r.x+r.w,r.y],[r.x,r.y+r.h],[r.x+r.w,r.y+r.h]],corner=corners.findIndex(([x,y])=>Math.hypot(p.x-x,p.y-y)<10);if(corner>=0){dragging={index,corner,original:{...r}};$('viewport').setPointerCapture(event.pointerId);event.preventDefault();break;}}}});
$('viewport').addEventListener('pointerup',()=>{if(['draw','pan'].includes(interaction.mode)&&interaction.held.has('L'))interaction.up('L',performance.now()-offset);dragging=null;});
$('viewport').addEventListener('scroll',updateView);
$('motion-zone').addEventListener('pointermove',event=>{const r=$('motion-zone').getBoundingClientRect(),x=(event.clientX-r.left-r.width/2)/(r.width/2)*14,y=(event.clientY-r.top-r.height/2)/(r.height/2)*14;interaction.tilt(x,y);interaction.move({x:520+x*8,y:300+y*8});});
$('motion-zone').addEventListener('pointerleave',()=>interaction.tilt(0,0));$('center').onclick=()=>interaction.tilt(0,0);
for(const [mode,label]of [['scroll','滚动'],['page','翻页'],['zoom','缩放'],['pan','平移'],['mark','标注'],['ai','AI 操作']]){const b=document.createElement('button');b.textContent=label;b.dataset.mode=mode;b.onpointerenter=()=>{selectedMode=mode;for(const x of $('radial-options').children)x.classList.toggle('selected',x===b);};b.onclick=()=>{selectedMode=mode;choose();};$('radial-options').append(b);}
$('clear-marks').onclick=()=>{regions=[];arrows=[];drawPoints=[];drawMarks();};
for(const b of document.querySelectorAll('[data-tool]'))b.onclick=()=>{drawTool=b.dataset.tool;interaction.drawTool=drawTool;for(const other of document.querySelectorAll('[data-tool]'))other.setAttribute('aria-pressed',String(other===b));};
$('type-instead').onclick=async()=>{try{await lockTarget();await claim();interaction.enter('review');phase('输入要求，确认后发送','文件快照已锁定，输入内容仍可编辑。');$('instruction').focus();}catch(e){notify(e.message,true);}};
$('instruction').addEventListener('input',updateButtons);$('cancel').onclick=()=>cancel().catch(e=>notify(e.message,true));
$('refresh').onclick=()=>readFile().catch(e=>notify(e.message,true));$('files').onchange=()=>cancel('已切换文件，需要重新锁定目标。').then(readFile).catch(e=>notify(e.message,true));
$('audio-file').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>2_000_000)throw new Error('录音最多 60 秒，需 16 kHz 单声道 PCM WAV');await lockTarget();await claim();interaction.enter('review');await recognize(await file.arrayBuffer());}catch(e){notify(e.message,true);}finally{event.target.value='';}};
$('send').onclick=async()=>{
  if(!context||context.sent||inference)return;const generation=epoch,c=context;c.sent=true;inference=true;$('instruction').disabled=true;updateButtons();interaction.enter('sending');phase('本地模型正在生成提案','当前文件尚未修改。你仍可取消本轮请求。');
  try{const result=await api('/api/send',{context_id:c.id,instruction:$('instruction').value,adapter:$('adapter').value,confirmed:true});if(generation!==epoch)return;proposal=result;$('comparison').hidden=false;$('summary').textContent=result.summary;compare('after');interaction.enter('compare');phase('检查修改，独立确认应用','对比只展示提案；点击确认应用才会写入文件。');notify('提案已收到，文件尚未修改。');}
  catch(e){if(generation===epoch){notify(e.message,true);phase('请求未完成','需要重新锁定目标后重试。文件没有因本次请求而修改。');}}
  finally{inference=false;updateButtons();}
};
for(const which of ['before','after','diff'])$(which+'-tab').onclick=()=>compare(which);
$('apply').onclick=async()=>{if(!proposal||changing)return;changing=true;updateButtons();try{receipt=await api('/api/apply',{proposal_id:proposal.id,confirmed:true});proposal=null;context=null;$('comparison').hidden=true;$('receipt').hidden=false;$('receipt').querySelector('.eyebrow').textContent='04 / 已核对结果';$('receipt-title').textContent='文件已写入并读回';$('receipt-details').textContent=`${receipt.path}\n回执 ${receipt.id}\nSHA256 ${receipt.after_sha256}`;phase('修改已经核对','可以查看工作区的实际文件，或撤销本次应用。');notify('修改已应用，并通过读回校验。');regions=[];arrows=[];await readFile();try{await claim();await command(7,1);}catch(e){notify('文件已核对；反馈命令失败：'+e.message,true);}interaction.enter('pointer');}catch(e){notify(e.message,true);}finally{changing=false;updateButtons();}};
$('undo').onclick=async()=>{if(!receipt||changing)return;changing=true;updateButtons();try{const result=await api('/api/undo',{receipt_id:receipt.id,confirmed:true});receipt=null;$('receipt-title').textContent='已撤销并读回原文';$('receipt-details').textContent=`${result.path}\n回执 ${result.id}\nSHA256 ${result.after_sha256}`;await readFile();notify('撤销完成，已读回核对原文。');}catch(e){notify(e.message,true);}finally{changing=false;updateButtons();}};
document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel('窗口隐藏，录音与增强操作已停止。').catch(()=>{});});
window.addEventListener('blur',()=>{if(rawMask||interaction.mode==='voice'||interaction.mode==='draw')cancel('窗口失焦，录音与按键已释放。').catch(()=>{});});
window.addEventListener('pagehide',()=>{recorder.cancel();fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-AIKEY-Session':token},body:'{}',keepalive:true}).catch(()=>{});});
try{const status=await api('/api/status');$('root-path').textContent=status.workspace;for(const name of status.files){const option=document.createElement('option');option.value=option.textContent=name;$('files').append(option);}deviceMode=status.device_mode;if(deviceMode==='ble')recorder=new NetworkRecorder(api);physicalDevice=status.physical_device;deviceReady=deviceMode!=='disconnected';if(deviceReady&&deviceMode!=='native-core-simulation'){document.querySelector('.controls').hidden=true;document.querySelector('.boundary').textContent='已接入 '+deviceMode.toUpperCase()+' 控制通道。输入来自实体按键；当前编辑范围是所选文本工作区。';}if(status.recovery.length)notify('检测到中断的事务，请先核对工作区日志。',true);await readFile();if(deviceReady){const fresh=await api('/api/device/connect');cursor=fresh.cursor;previousButtons=fresh.state.buttons;offset=performance.now()-fresh.state.time_ms;inputReady=true;lastSession=fresh.state.session;}await pulse();$('connection').textContent=deviceReady?(deviceMode==='native-core-simulation'?'本地已连接 · 固件模拟':'本地已连接 · '+deviceMode.toUpperCase()):'本地已连接 · 未连接设备';setInterval(pulse,40);}catch(error){notify(error.message,true);}
