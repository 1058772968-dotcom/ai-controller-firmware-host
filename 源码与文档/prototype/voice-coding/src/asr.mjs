// 语音转文字：百炼 qwen3-asr-flash（原生多模态接口，音频走 base64 data URI）。
// 一次请求一段音频，不做流式；按住说话的场景，整段识别比流式更好改。
import { parseWav } from './wav.mjs';

export class AsrError extends Error {
  constructor(message, { status = 0, kind = 'unknown', detail = '' } = {}) {
    super(message);
    this.name = 'AsrError';
    this.status = status || undefined; // 0 表示没有 HTTP 状态码，别让上层把它当状态码用
    this.kind = kind;
    this.detail = detail;
  }
}

export function buildRequest(wavBytes, { baseUrl, model, language, hotwords }) {
  if (!baseUrl) throw new AsrError('没有配置 ASR 地址', { kind: 'config' });
  if (!model) throw new AsrError('没有配置 ASR 模型', { kind: 'config' });
  const audio = `data:audio/wav;base64,${Buffer.from(wavBytes).toString('base64')}`;
  const body = {
    model,
    input: { messages: [{ role: 'user', content: [{ audio }] }] },
  };
  const options = {};
  if (language) options.language = language;
  if (hotwords) options.context = { text: hotwords };
  options.enable_itn = true;
  body.parameters = { asr_options: options };
  return {
    url: `${baseUrl.replace(/\/+$/, '')}/api/v1/services/aigc/multimodal-generation/generation`,
    body,
  };
}

const pick = (v) => (typeof v === 'string' ? v : '');
export function extractText(payload) {
  const content = payload?.output?.choices?.[0]?.message?.content;
  if (typeof content === 'string') return pick(content);
  if (Array.isArray(content)) {
    return content.map((part) => (typeof part === 'string' ? part : pick(part?.text))).join('').trim();
  }
  return '';
}

function describeError(status, text) {
  let code = '';
  try {
    const json = JSON.parse(text);
    code = json.code || json.error?.code || '';
  } catch {
    // 非 JSON 响应照样往下走，只保留截断原文
  }
  const detail = `${status} ${code} ${text.slice(0, 300)}`.trim();
  if (status === 401 || status === 403) return new AsrError('ASR 密钥无效或没有这个模型的权限', { status, kind: 'auth', detail });
  if (status === 429) return new AsrError('ASR 被限流，稍等一下再按一次', { status, kind: 'rate', detail });
  if (status === 400) return new AsrError(`ASR 说参数不对：${code || 'BadRequest'}`, { status, kind: 'request', detail });
  if (status >= 500) return new AsrError('ASR 服务端出错，稍后重试', { status, kind: 'server', detail });
  return new AsrError(`ASR 调用失败（HTTP ${status}）`, { status, kind: 'http', detail });
}

export async function transcribe(wavBytes, {
  apiKey,
  config,
  fetchImpl = globalThis.fetch,
  retries = 1,
  now = () => Date.now(),
} = {}) {
  if (!apiKey) throw new AsrError('没有找到 ASR 密钥（钥匙串 voice-coding-bailian 或环境变量 DASHSCOPE_API_KEY）', { kind: 'auth' });
  const wav = parseWav(wavBytes);
  const maxMs = (config.audio?.maxSeconds ?? 90) * 1000;
  const minMs = (config.audio?.minSeconds ?? 0) * 1000;
  if (wav.durationMs > maxMs) {
    throw new AsrError(`这段录音 ${(wav.durationMs / 1000).toFixed(1)} 秒，超过上限 ${(maxMs / 1000).toFixed(0)} 秒`, { kind: 'audio' });
  }
  if (wav.durationMs < minMs) {
    throw new AsrError(`这段录音只有 ${wav.durationMs} 毫秒，太短了`, { kind: 'audio' });
  }
  const { url, body } = buildRequest(wavBytes, config.asr);
  const started = now();
  let lastError = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const res = await fetchImpl(url, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(config.asr.timeoutMs ?? 45000),
      });
      const text = await res.text();
      if (!res.ok) {
        const err = describeError(res.status, text);
        // 只有服务端 5xx / 429 值得再试一次，鉴权和参数错误重试也没用
        if ((res.status >= 500 || res.status === 429) && attempt < retries) { lastError = err; continue; }
        throw err;
      }
      let payload;
      try {
        payload = JSON.parse(text);
      } catch {
        throw new AsrError('ASR 返回的不是 JSON', { kind: 'response', detail: text.slice(0, 200) });
      }
      const out = extractText(payload);
      if (!out) throw new AsrError('ASR 没识别出内容（是不是没说话，或者麦克风没开闸）', { kind: 'empty' });
      return {
        text: out,
        model: body.model,
        durationMs: wav.durationMs,
        elapsedMs: now() - started,
        audioSeconds: payload?.usage?.seconds ?? null,
        requestId: payload?.request_id ?? '',
        emotion: payload?.output?.choices?.[0]?.message?.annotations?.[0]?.emotion ?? '',
      };
    } catch (err) {
      if (err instanceof AsrError) {
        if (err.kind === 'server' || err.kind === 'rate') { lastError = err; if (attempt < retries) continue; }
        throw err;
      }
      if (err?.name === 'TimeoutError' || err?.name === 'AbortError') {
        throw new AsrError('ASR 超时了，检查网络或把超时调长', { kind: 'timeout', detail: err.message });
      }
      throw new AsrError(`连不上 ASR：${err.message}`, { kind: 'network', detail: err.message });
    }
  }
  throw lastError ?? new AsrError('ASR 失败', { kind: 'unknown' });
}
