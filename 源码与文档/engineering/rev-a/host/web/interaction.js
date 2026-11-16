export const TIMING={side:180,voice:280,double:300,page:54,dead:2,maxAngle:14};
export const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
export function velocity(angle,slow=false){const a=Math.abs(angle);return a<=TIMING.dead?0:Math.sign(angle)*Math.pow(clamp((a-TIMING.dead)/(TIMING.maxAngle-TIMING.dead),0,1),1.65)*850*(slow?.18:1);}
export function boxFromPoints(points,width=1040,height=1700){if(points.length<3)return null;const xs=points.map(p=>p.x),ys=points.map(p=>p.y),x=clamp(Math.min(...xs),0,width),y=clamp(Math.min(...ys),0,height),right=clamp(Math.max(...xs),0,width),bottom=clamp(Math.max(...ys),0,height);return right-x<14||bottom-y<14?null:{x,y,w:right-x,h:bottom-y};}
export class Interaction{
  constructor(emit=()=>{}){this.emit=emit;this.mode='pointer';this.held=new Map();this.blocked=new Set();this.point={x:520,y:300};this.angle={x:0,y:0};this.lastVoice=-Infinity;this.pageDelta=0;this.connected=true;this.slow=false;this.drawTool='region';this.compareReady=true;}
  send(type,extra={}){this.emit({type,mode:this.mode,...extra});}
  enter(mode){this.angle={x:0,y:0};this.slow=false;this.mode=mode;this.pageDelta=0;this.compareReady=true;this.send('mode');}
  down(key,t=performance.now()){
    if(this.held.has(key)||this.blocked.has(key)||!this.connected)return;
    if(key==='R'&&this.mode!=='pointer'){this.blocked.add(key);this.cancel('R 退出');return;}
    if(this.held.size){this.send('blocked');return;}
    const h={at:t,start:{...this.point},active:false};this.held.set(key,h);
    this.send('edge',{key,edge:'down'});
    if(key==='L'){
      if(this.mode==='pointer')this.send('mouse',{button:'left',edge:'down'});
      else if(this.mode==='radial')this.send('choose');
      else if(this.mode==='scroll'){this.slow=true;this.send('slow',{active:true});}
      else if(this.mode==='pan')this.send('pan-start');
      else if(this.mode==='mark'){h.active=true;this.enter('draw');this.send('draw-start',{tool:this.drawTool});}
    }
    if(key==='R')this.send('mouse',{button:'right',edge:'down'});
    if(key==='V'){this.send('voice-arm',{point:{...this.point}});}
    if(key==='S'&&this.mode==='page'){this.pageDelta=0;this.send('page-preview',{direction:0});}
  }
  up(key,t=performance.now()){
    this.blocked.delete(key);const h=this.held.get(key);if(!h)return;this.held.delete(key);this.send('edge',{key,edge:'up'});
    if(key==='L'){
      if(this.mode==='pointer')this.send('mouse',{button:'left',edge:'up'});
      else if(this.mode==='scroll'){this.slow=false;this.send('slow',{active:false});}
      else if(this.mode==='draw'&&h.active){this.send('draw-end',{tool:this.drawTool});this.enter('pointer');}
      else if(this.mode==='pan')this.send('pan-end');
      else if(['review','compare','sending'].includes(this.mode))this.send('ui-click');
    }
    if(key==='R')this.send('mouse',{button:'right',edge:'up'});
    if(key==='S'){
      if(this.mode==='page'){const direction=Math.abs(this.pageDelta)>=TIMING.page?Math.sign(this.pageDelta):0;this.send('page-commit',{direction});this.pageDelta=0;}
      else if(this.mode==='draw'&&h.active){this.send('draw-end',{tool:this.drawTool});this.enter('pointer');}
      else if(!h.active){if(this.mode==='pointer')this.enter('radial');else if(['scroll','radial','zoom','pan','mark','laser'].includes(this.mode))this.cancel('S 退出');}
    }
    if(key==='V'){
      if(h.active){this.lastVoice=-Infinity;this.enter('review');this.send('voice-preview');}
      else if(t-this.lastVoice<=TIMING.double){this.lastVoice=-Infinity;this.angle={x:0,y:0};this.send('recenter');}
      else {this.lastVoice=t;this.send('voice-disarm');}
    }
  }
  move(point){
    const old=this.point;this.point={...point};
    if(this.mode==='draw')this.send('draw-point',{point});
    if(this.mode==='page'&&this.held.has('S')){this.pageDelta=point.x-this.held.get('S').start.x;this.send('page-preview',{direction:Math.abs(this.pageDelta)>=TIMING.page?Math.sign(this.pageDelta):0,delta:this.pageDelta});}
    if(this.mode==='pan'&&this.held.has('L'))this.send('pan',{dx:point.x-old.x,dy:point.y-old.y});
    if(this.mode==='pointer'&&this.held.has('L'))this.send('drag',{point});
  }
  tilt(x,y){this.angle={x:clamp(x,-14,14),y:clamp(y,-14,14)};if(this.mode==='compare'){if(Math.abs(x)<2)this.compareReady=true;else if(Math.abs(x)>6&&this.compareReady){this.compareReady=false;this.send('compare',{after:x>0});}}}
  tick(t,dt=0){
    if(!this.connected)return;
    for(const [key,h] of this.held){
      if(key==='S'&&this.mode==='pointer'&&!h.active&&t-h.at>=TIMING.side){h.active=true;this.enter('draw');this.send('draw-start',{tool:this.drawTool,point:h.start});}
      if(key==='V'&&!h.active&&t-h.at>=TIMING.voice){h.active=true;this.lastVoice=-Infinity;this.enter('voice');this.send('voice-start');}
    }
    const step=Math.min(dt,.05);
    if(this.mode==='scroll')this.send('scroll',{speed:velocity(this.angle.y,this.slow),delta:velocity(this.angle.y,this.slow)*step});
    if(this.mode==='zoom'&&Math.abs(this.angle.x)>2)this.send('zoom',{delta:this.angle.x*.0025*step});
  }
  arm(tool='region'){this.drawTool=tool;this.enter('mark');}
  cancel(reason='退出'){
    for(const [key] of this.held){this.blocked.add(key);if(key==='L'||key==='R')this.send('mouse',{button:key==='L'?'left':'right',edge:'up',cancelled:true});}
    this.held.clear();this.lastVoice=-Infinity;this.enter('pointer');this.send('cancel',{reason});
  }
  disconnect(){this.cancel('设备断连');this.connected=false;this.send('connection',{connected:false});}
  reconnect(){this.connected=true;this.cancel('设备已重连');this.send('connection',{connected:true});}
}
