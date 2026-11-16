// 从 E24 麦克风取流。语音处理全关，否则系统降噪和自动增益会改掉“全零”这个判据。
// 联调档叫 Held-key microphone；POC 档叫 AI KEY Mic POC，主机开流即放行，闸门判据不适用。
export const POC_MIC = 'AI KEY Mic POC';
export const MIC_NAMES = ['Held-key microphone', POC_MIC];
export const pickMic = (list) => list.find((d) => d.kind === 'audioinput' && MIC_NAMES.some((n) => d.label.includes(n)));

async function findMic() {
  let list = await navigator.mediaDevices.enumerateDevices();
  if (!list.some((d) => d.kind === 'audioinput' && d.label)) {
    // 没授权时看不到设备名：申请一次权限后马上关掉，不读数据
    const s = await navigator.mediaDevices.getUserMedia({ audio: true });
    s.getTracks().forEach((t) => t.stop());
    list = await navigator.mediaDevices.enumerateDevices();
  }
  const mic = pickMic(list);
  if (!mic) throw new Error(`系统里没有 ${MIC_NAMES.join(' 或 ')}：确认烧的是带音频的固件`);
  return mic;
}

export async function openMic() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('这个页面不能取麦克风，请从 http://127.0.0.1 打开');
  let stream, mic;
  try {
    mic = await findMic();
    const deviceId = mic.deviceId;
    stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: { exact: deviceId }, echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
  } catch (err) {
    if (err.name === 'NotAllowedError') throw new Error('麦克风权限被拒绝：在地址栏左边的站点设置里允许后再试');
    throw err;
  }
  const ctx = new AudioContext({ sampleRate: 16000 });
  await ctx.resume();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(1024, 1, 1); // 台架工具，主线程处理够用
  const sink = ctx.createGain(); sink.gain.value = 0;  // 不外放，免得啸叫
  const cap = {
    onBlock: null,
    poc: mic.label.includes(POC_MIC),
    async close() { proc.onaudioprocess = null; src.disconnect(); proc.disconnect(); sink.disconnect(); stream.getTracks().forEach((t) => t.stop()); await ctx.close(); },
  };
  proc.onaudioprocess = (e) => cap.onBlock?.(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(proc); proc.connect(sink); sink.connect(ctx.destination);
  return cap;
}
