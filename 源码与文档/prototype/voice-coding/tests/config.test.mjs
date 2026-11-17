import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { mkdtemp, readFile, stat } from 'node:fs/promises';
import { defaultConfig, normalizeConfig, routeByPrefix, loadConfig, saveConfig, agentById } from '../src/config.mjs';

test('空配置得到默认值，默认 Agent 至少覆盖终端和跟随前台', () => {
  const { config } = normalizeConfig(null);
  assert.equal(config.version, 1);
  assert.equal(config.asr.model, 'qwen3-asr-flash');
  assert.equal(config.behavior.autoSend, false);
  assert.ok(agentById(config, 'claude-code'));
  assert.ok(agentById(config, 'frontmost'));
});

test('坏 Agent 被丢掉并回报问题，好的保留', () => {
  const { config, issues } = normalizeConfig({
    agents: [
      { id: 'ok', name: '好家伙', app: { bundleId: 'com.example.ok' }, send: 'cmd-return' },
      { name: '没有应用' },
      'not-an-object',
      { name: '重复编号', id: 'ok', app: { name: 'Safari' } },
    ],
  });
  // 「没有应用」不是错，那是「跟着前台走」；只有根本不是对象的那项被丢掉
  assert.equal(config.agents.length, 3);
  assert.deepEqual(config.agents.map((a) => a.id), ['ok', 'agent-2', 'ok-2']);
  assert.equal(config.agents[0].send, 'cmd-return');
  assert.deepEqual(config.agents[1].app, { bundleId: '', name: '' });
  assert.ok(issues.some((i) => i.path === 'agents[2]'));
});

test('数值越界会被夹住，而不是让服务崩', () => {
  const { config } = normalizeConfig({ audio: { maxSeconds: 9999, minSeconds: -5 }, asr: { timeoutMs: 1 } });
  assert.equal(config.audio.maxSeconds, 600);
  assert.equal(config.audio.minSeconds, 0);
  assert.equal(config.asr.timeoutMs, 3000);
});

test('语音前缀只在有分隔符时才路由', () => {
  const { config } = normalizeConfig(null);
  const hit = routeByPrefix(config, 'Claude，帮我加一个单元测试');
  assert.equal(hit.agentId, 'claude-code');
  assert.equal(hit.text, '帮我加一个单元测试');
  const colon = routeByPrefix(config, 'cursor: 把这段重命名');
  assert.equal(colon.agentId, 'cursor');
  assert.equal(colon.text, '把这段重命名');
  const none = routeByPrefix(config, 'Cursor里那个函数报错了');
  assert.equal(none.agentId, null);
  assert.equal(none.text, 'Cursor里那个函数报错了');
  const plain = routeByPrefix(config, '加一个单元测试');
  assert.equal(plain.agentId, null);
});

test('长别名优先，停用的 Agent 不参与路由', () => {
  const { config } = normalizeConfig({
    agents: [
      { id: 'cc', name: 'Claude Code', aliases: ['cc'], app: { name: 'A' } },
      { id: 'c', name: 'cc', aliases: [], app: { name: 'B' } },
      { id: 'off', name: '离线', app: { name: 'C' }, enabled: false },
    ],
  });
  const hit = routeByPrefix(config, 'Claude Code：跑一下测试');
  assert.equal(hit.agentId, 'cc');
  assert.equal(hit.text, '跑一下测试');
  assert.equal(routeByPrefix(config, '离线，做点事').agentId, null);
});

test('关掉前缀路由就原样返回', () => {
  const { config } = normalizeConfig({ behavior: { prefixRouting: false } });
  const hit = routeByPrefix(config, 'Claude，别动');
  assert.equal(hit.agentId, null);
  assert.equal(hit.text, 'Claude，别动');
});

test('存盘是原子写且权限 600，读回来一致', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'vc-cfg-'));
  const file = path.join(dir, 'config.json');
  const { config } = normalizeConfig(defaultConfig());
  config.behavior.autoSend = true;
  await saveConfig(config, file);
  const mode = (await stat(file)).mode & 0o777;
  assert.equal(mode, 0o600);
  const raw = JSON.parse(await readFile(file, 'utf8'));
  assert.equal(raw.behavior.autoSend, true);
  const back = await loadConfig(file);
  assert.equal(back.existed, true);
  assert.deepEqual(back.issues, []);
  assert.equal(back.config.agents.length, config.agents.length);
});

test('配置文件坏了不抛错，说明原因后用默认值', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'vc-cfg-'));
  const file = path.join(dir, 'config.json');
  await import('node:fs/promises').then((fs) => fs.writeFile(file, '{not json'));
  const back = await loadConfig(file);
  assert.equal(back.existed, false);
  assert.ok(back.issues[0].message.includes('配置读取失败'));
  assert.ok(back.config.agents.length > 0);
});
