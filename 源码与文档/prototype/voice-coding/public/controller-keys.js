// 手柄四键 → 界面动作。默认绑 V，因为固件的隐私闸门就是「按住 V 才放行麦克风」：
// ak_mic_permitted() 要求 recording + mic_power + mic_ready + HOST + (V 按住)。
// 换成 L/R/S 录音，麦克风不会开，录到的只会是全零。
export const BUTTONS = { L: 1, R: 2, V: 4, S: 8 };
export const RECORD_KEY = 'V';

export const KEY_ROLES = {
  V: '按住录音',
  L: '填入并发送',
  R: '清空',
  S: '未绑定',
};

// down=true 是按下，false 是松开；返回界面该做什么
export function mapControllerKey(name, down, { recording = false, hasTranscript = false } = {}) {
  const key = String(name ?? '').toUpperCase();
  if (!(key in BUTTONS)) return { action: 'none', reason: '不认识的键' };
  if (key === RECORD_KEY) {
    if (down && !recording) return { action: 'record-start', reason: '' };
    if (!down && recording) return { action: 'record-stop', reason: '' };
    return { action: 'none', reason: down ? '已经在录音了' : '本来就没在录' };
  }
  if (!down) return { action: 'none', reason: '' }; // L/R/S 只认按下，松开不做事
  if (key === 'L') return hasTranscript ? { action: 'send', reason: '' } : { action: 'none', reason: '还没有文字可发' };
  if (key === 'R') return { action: 'clear', reason: '' };
  return { action: 'none', reason: 'S 键还没绑功能' };
}
