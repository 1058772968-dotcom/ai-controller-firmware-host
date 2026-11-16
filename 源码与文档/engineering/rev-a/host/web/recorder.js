// Browser capture is explicit and limited to a held trigger. No audio survives cancel.
export class HeldRecorder {
  constructor(){this.generation=0;this.stream=null;this.context=null;this.processor=null;this.chunks=[];this.limit=null;}
  async start(onLimit,requiredDeviceLabel=null){
    const generation=++this.generation;this.chunks=[];
    const audio={channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false};
    if(requiredDeviceLabel){
      const devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='audioinput'&&requiredDeviceLabel.test(d.label));
      if(devices.length!==1)throw new Error('未找到唯一 AI KEY 麦克风。请在浏览器麦克风设置中授权并选择 AI KEY，再重新按住 V。');
      audio.deviceId={exact:devices[0].deviceId};
    }
    const stream=await navigator.mediaDevices.getUserMedia({audio,video:false});
    if(generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return false;}
    this.stream=stream;this.context=new AudioContext();await this.context.resume();
    if(generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return false;}
    this.rate=this.context.sampleRate;const source=this.context.createMediaStreamSource(stream);
    this.processor=this.context.createScriptProcessor(4096,1,1);
    this.processor.onaudioprocess=e=>{if(generation===this.generation)this.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));e.outputBuffer.getChannelData(0).fill(0);};
    source.connect(this.processor);this.processor.connect(this.context.destination);
    this.limit=setTimeout(()=>{this.cancel();onLimit();},60000);return true;
  }
  detach(){
    ++this.generation;clearTimeout(this.limit);this.limit=null;
    if(this.processor){this.processor.onaudioprocess=null;this.processor.disconnect();this.processor=null;}
    if(this.stream){this.stream.getTracks().forEach(t=>t.stop());this.stream=null;}
    if(this.context){this.context.close();this.context=null;}
  }
  cancel(){this.detach();this.chunks=[];}
  async stop(){
    const chunks=this.chunks,rate=this.rate;this.detach();this.chunks=[];
    const length=chunks.reduce((n,c)=>n+c.length,0);if(!length)return null;
    const pcm=new Float32Array(length);let at=0;for(const c of chunks){pcm.set(c,at);at+=c.length;}
    // OfflineAudioContext performs browser sample-rate conversion before PCM packing.
    const count=Math.ceil(length*16000/rate),offline=new OfflineAudioContext(1,count,16000),buffer=offline.createBuffer(1,length,rate);
    buffer.copyToChannel(pcm,0);const source=offline.createBufferSource();source.buffer=buffer;source.connect(offline.destination);source.start();
    const rendered=(await offline.startRendering()).getChannelData(0),bytes=new ArrayBuffer(44+count*2),view=new DataView(bytes);
    const text=(at,s)=>{for(let i=0;i<s.length;i++)view.setUint8(at+i,s.charCodeAt(i));};
    text(0,'RIFF');view.setUint32(4,36+count*2,true);text(8,'WAVEfmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,count*2,true);
    for(let i=0;i<count;i++)view.setInt16(44+i*2,Math.round(Math.max(-1,Math.min(1,rendered[i]))*32767),true);
    return bytes;
  }
}
export function base64(bytes){let result='';const a=new Uint8Array(bytes);for(let i=0;i<a.length;i+=16384)result+=String.fromCharCode(...a.subarray(i,i+16384));return btoa(result);}

// BLE controls the held trigger; PCM arrives at the companion over TLS/Wi-Fi.
// This recorder never asks for browser microphone access.
export class NetworkRecorder {
  constructor(api){this.api=api;this.active=false;this.limit=null;this.pending=null;this.generation=0;}
  async start(onLimit){this.generation++;this.active=true;this.pending=null;this.limit=setTimeout(()=>{this.cancel();onLimit();},60000);return true;}
  cancel(){this.generation++;this.active=false;clearTimeout(this.limit);this.limit=null;this.pending=null;this.api('/api/audio/cancel').catch(()=>{});}
  async stop(){
    if(this.pending)return this.pending;
    if(!this.active)return null;
    this.active=false;clearTimeout(this.limit);this.limit=null;const generation=this.generation;
    this.pending=this.api('/api/audio/finish').then(result=>{
      if(generation!==this.generation)return null;
      const text=atob(result.wav_base64),out=new Uint8Array(text.length);for(let i=0;i<text.length;i++)out[i]=text.charCodeAt(i);return out.buffer;
    });return this.pending;
  }
}
