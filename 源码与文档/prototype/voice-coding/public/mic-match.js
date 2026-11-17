// 只认板子（E24 手柄）暴露的 USB 麦克风，不认电脑内置麦、手机麦、聚合设备。
// 纯函数，方便在 Node 里直接测：设备列表长什么样由浏览器给，判断规则只在这里。
export const DEFAULT_BOARD_MIC_NAMES = ['Held-key microphone', 'AI KEY Mic POC'];

const lower = (v) => String(v ?? '').toLowerCase();

export function isBoardMic(label, names = DEFAULT_BOARD_MIC_NAMES) {
  const text = lower(label);
  if (!text) return false; // 没授权时 label 是空的，不能猜
  return (names || [])
    .map((n) => lower(n).trim())
    .filter(Boolean)
    .some((name) => text.includes(name));
}

// 设备列表 → 板载麦克风；preferredDeviceId 只在它本身也是板载麦时才用
export function pickBoardMic(devices, { names = DEFAULT_BOARD_MIC_NAMES, preferredDeviceId = '' } = {}) {
  const inputs = (devices || []).filter((d) => d && d.kind === 'audioinput');
  if (preferredDeviceId) {
    const preferred = inputs.find((d) => d.deviceId === preferredDeviceId);
    if (preferred && isBoardMic(preferred.label, names)) return preferred;
  }
  return inputs.find((d) => isBoardMic(d.label, names)) || null;
}

// 按不按开始录音：只认板子时，没有板载麦克风就不许录（返回原因，界面据此提示）
export function resolveStartTarget({ requireBoardMic = true, micView = null, micId = '' } = {}) {
  const view = micView || { board: [], state: 'unauthorized' };
  if (!requireBoardMic) return { ok: true, deviceId: micId || '', reason: '' };
  const board = view.board || [];
  if (!board.length) {
    return { ok: false, deviceId: '', reason: view.state === 'unauthorized' ? 'unauthorized' : 'missing' };
  }
  const chosen = board.find((d) => d.deviceId === micId) || board[0];
  return { ok: true, deviceId: chosen.deviceId, reason: '' };
}

// 给界面用：分开「板载的」和「其它的」，并说清楚现在是什么状态
export function describeMics(devices, { names = DEFAULT_BOARD_MIC_NAMES, preferredDeviceId = '' } = {}) {
  const inputs = (devices || []).filter((d) => d && d.kind === 'audioinput');
  const labelsVisible = inputs.some((d) => String(d.label || '').trim());
  const board = inputs.filter((d) => isBoardMic(d.label, names));
  const others = inputs.filter((d) => !isBoardMic(d.label, names));
  return {
    inputs,
    board,
    others,
    labelsVisible,
    picked: pickBoardMic(inputs, { names, preferredDeviceId }),
    state: board.length ? 'ready' : labelsVisible ? 'missing' : 'unauthorized',
  };
}
