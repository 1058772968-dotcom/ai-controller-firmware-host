import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRequest, extractText, transcribe, AsrError } from '../src/asr.mjs';
import { pcm16ToWav } from '../src/wav.mjs';
import { normalizeConfig } from '../src/config.mjs';

const wav = (ms = 1500) => pcm16ToWav(new Uint8Array(Math.round((16000 * ms) / 1000) * 2));
const cfg = (patch = {}) => {
  const base = normalizeConfig(null).config;
  base.asr.timeoutMs = 5000;
  return { ...base, ...patch, asr: { ...base.asr, ...(patch.asr ?? {}) } };
};
const ok = (text = '帮我把按钮改成蓝色', extra = {}) => async () => ({
  ok: true,
  status: 200,
  text: async () => JSON.stringify({
    output: { choices: [{ message: { content: [{ text }] }, annotations: [{ emotion: 'neutral' }] }] },
    usage: { seconds: 2 },
    request_id: 'req-1',
    ...extra,
  }),
});

test('请求地址、模型和音频编码都对', () => {
  const { url, body } = buildRequest(wav(), cfg().asr);
  assert.equal(url, 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation');
  assert.equal(body.model, 'qwen3-asr-flash');
  const audio = body.input.messages[0].content[0].audio;
  assert.ok(audio.startsWith('data:audio/wav;base64,UklGR'));
  assert.equal(body.parameters.asr_options.language, 'zh');
  assert.equal(body.parameters.asr_options.enable_itn, true);
  assert.ok(body.parameters.asr_options.context.text.includes('Claude Code'));
});

test('地址末尾多余斜杠不会拼出双斜杠', () => {
  const { url } = buildRequest(wav(), { baseUrl: 'https://x.example.com/', model: 'm' });
  assert.ok(url.startsWith('https://x.example.com/api/v1'));
});

test('返回结构两种写法都能取到文字', () => {
  assert.equal(extractText({ output: { choices: [{ message: { content: '纯文本' } }] } }), '纯文本');
  assert.equal(extractText({ output: { choices: [{ message: { content: [{ text: '一' }, { text: '二' }] } }] } }), '一二');
  assert.equal(extractText({}), '');
});

test('正常识别：文字、时长、耗时都有', async () => {
  const res = await transcribe(wav(2000), { apiKey: 'k', config: cfg(), fetchImpl: ok() });
  assert.equal(res.text, '帮我把按钮改成蓝色');
  assert.equal(res.durationMs, 2000);
  assert.equal(res.model, 'qwen3-asr-flash');
  assert.equal(res.requestId, 'req-1');
  assert.equal(res.audioSeconds, 2);
  assert.ok(res.elapsedMs >= 0);
});

test('带的 Authorization 就是密钥本身，请求体是 JSON', async () => {
  let seen = null;
  const fetchImpl = async (url, init) => {
    seen = { url, init };
    return (await ok()());
  };
  await transcribe(wav(), { apiKey: 'sk-test', config: cfg(), fetchImpl });
  assert.equal(seen.init.headers.Authorization, 'Bearer sk-test');
  assert.equal(seen.init.method, 'POST');
  assert.ok(JSON.parse(seen.init.body).input.messages);
});

test('鉴权失败不重试，错误话说得清楚', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls += 1; return { ok: false, status: 401, text: async () => '{"code":"InvalidApiKey"}' }; };
  await assert.rejects(() => transcribe(wav(), { apiKey: 'k', config: cfg(), fetchImpl }), (err) => {
    assert.ok(err instanceof AsrError);
    assert.equal(err.kind, 'auth');
    assert.match(err.message, /密钥/);
    return true;
  });
  assert.equal(calls, 1);
});

test('服务端 500 会重试一次，仍失败就报服务端错误', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls += 1; return { ok: false, status: 503, text: async () => 'upstream down' }; };
  await assert.rejects(() => transcribe(wav(), { apiKey: 'k', config: cfg(), fetchImpl }), (err) => err.kind === 'server');
  assert.equal(calls, 2);
});

test('限流后重试成功照样返回文字', async () => {
  let calls = 0;
  const fetchImpl = async (url, init) => {
    calls += 1;
    if (calls === 1) return { ok: false, status: 429, text: async () => '{"code":"Throttling"}' };
    return ok('第二次成功')(url, init);
  };
  const res = await transcribe(wav(), { apiKey: 'k', config: cfg(), fetchImpl });
  assert.equal(res.text, '第二次成功');
  assert.equal(calls, 2);
});

test('没识别出文字算明确错误，不返回空串', async () => {
  await assert.rejects(() => transcribe(wav(), { apiKey: 'k', config: cfg(), fetchImpl: ok('') }), (err) => err.kind === 'empty');
});

test('太短、太长在发请求前就拦住', async () => {
  let called = 0;
  const fetchImpl = async () => { called += 1; return ok()(); };
  await assert.rejects(() => transcribe(wav(100), { apiKey: 'k', config: cfg(), fetchImpl }), (err) => err.kind === 'audio');
  const longCfg = cfg({ audio: { maxSeconds: 1, minSeconds: 0.1 } });
  await assert.rejects(() => transcribe(wav(2000), { apiKey: 'k', config: longCfg, fetchImpl }), (err) => /超过上限/.test(err.message));
  assert.equal(called, 0);
});

test('没有密钥时不去打网络', async () => {
  let called = 0;
  await assert.rejects(() => transcribe(wav(), { apiKey: '', config: cfg(), fetchImpl: async () => { called += 1; } }), (err) => err.kind === 'auth');
  assert.equal(called, 0);
});

test('超时和断网各有各的说法', async () => {
  const timeout = async () => { const e = new Error('timed out'); e.name = 'TimeoutError'; throw e; };
  await assert.rejects(() => transcribe(wav(), { apiKey: 'k', config: cfg(), fetchImpl: timeout }), (err) => err.kind === 'timeout');
  const offline = async () => { throw new TypeError('fetch failed'); };
  await assert.rejects(() => transcribe(wav(), { apiKey: 'k', config: cfg(), fetchImpl: offline }), (err) => err.kind === 'network');
});

test('返回非 JSON 也当成错误，不把浏览器错误页当文字', async () => {
  const fetchImpl = async () => ({ ok: true, status: 200, text: async () => '<html>502</html>' });
  await assert.rejects(() => transcribe(wav(), { apiKey: 'k', config: cfg(), fetchImpl }), (err) => err.kind === 'response');
});
