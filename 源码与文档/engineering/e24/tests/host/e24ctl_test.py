#!/usr/bin/env python3
"""e24ctl.py 的电脑端测试。对端是 devcfg_shim（固件同一份 C 代码），不是 Python 自己。
用法：e24ctl_test.py <devcfg_shim 可执行文件>
只证明帧格式、参数编码、轴向推导和流程逻辑；不证明 USB、hidapi 读写或真机手感。"""
import contextlib
import io
import itertools
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import e24ctl as T  # noqa: E402

SHIM = sys.argv[1]


class Shim:
    def __init__(self):
        self.p = subprocess.Popen([SHIM], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def cmd(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        return self.p.stdout.readline().strip()

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)
        assert self.p.returncode == 0, f"shim 退出码 {self.p.returncode}（ASan/UBSan 报错会到这里）"


class ShimTransport:
    """像 hidapi 一样：写报告 3，读到回复；没有回复时读到周期状态报告 2。"""

    def __init__(self, shim):
        self.s = shim
        self.q = []
        self.cmd_results = []

    def write(self, data):
        if data[0] == T.REPORT_STATE:          # 控制命令：交给固件 ak_command，记下结果码
            assert len(data) == 33
            r = self.s.cmd("cmd " + data[1:].hex())
            assert r.startswith("C "), r
            self.cmd_results.append((data[2], int(r[2:])))
            return
        assert data[0] == T.REPORT_CFG and len(data) == 33
        r = self.s.cmd("cfg " + data[1:].hex())
        assert r.startswith("R "), r
        self.q.append(bytes([T.REPORT_CFG]) + bytes.fromhex(r[2:]))

    def read(self, timeout_ms):
        if self.q:
            return self.q.pop(0)
        r = self.s.cmd("status")
        assert r.startswith("S "), r
        return bytes([T.REPORT_STATE]) + bytes.fromhex(r[2:])


class FakeClock:
    """让 collect()/wait_calibrated() 按仿真时间走，结果确定。"""

    def __init__(self):
        self.now = 0.0
        self.tel = None

    def monotonic(self):
        self.now += 1e-5
        return self.now

    def sleep(self, s):
        if self.tel:
            self.tel.advance(s)
        self.now += s


class SimTelemetry:
    """把设备坐标系下的姿势/转动换到传感器坐标，喂给真实 pointer.c，再以遥测格式返回。"""

    def __init__(self, shim, clock, mount):
        self.s, self.clock, self.m = shim, clock, mount
        self.g_dev, self.a_dev = [0, 0, 0], [0, 0, 1]
        self.t = 0
        clock.tel = self

    def to_sensor(self, v):
        return [sum(self.m[k][i] * v[i] for i in range(3)) for k in range(3)]

    def pose(self, a_dev, g_dev=(0, 0, 0)):
        self.a_dev, self.g_dev = list(a_dev), list(g_dev)

    def _feed(self, n):
        g, a = self.to_sensor(self.g_dev), self.to_sensor(self.a_dev)
        r = self.s.cmd("feed " + " ".join(f"{x:.4f}" for x in g + a) + f" {n}").split()
        assert r[0] == "F", r
        self.t += 5 * n
        return {"v": 1, "type": "imu", "t": self.t, "dt": 0.005, "g": g, "a": a, "h": float(r[4]), "vv": float(r[5]),
                "dx": int(r[1]), "dy": int(r[2]), "bias": [float(x) for x in r[7:10]], "cal": int(r[3]),
                "still": int(r[6])}

    def advance(self, seconds):
        self._feed(max(1, int(seconds * 200)))

    def read(self, timeout=0.2):
        self.clock.now += 0.01      # 100 Hz 遥测 = 每条 2 个样本
        return self._feed(2)

    def flush(self):
        pass


class ScriptUI:
    def __init__(self, steps):
        self.steps = list(steps)
        self.said = []

    def say(self, m):
        self.said.append(m)

    def wait_enter(self, m):
        self.said.append(m)
        self.steps.pop(0)()

    def confirm(self, m):
        return True


def new_dev():
    sh = Shim()
    return sh, T.E24(ShimTransport(sh), log=lambda m: None)


def test_frames_and_defaults():
    sh, d = new_dev()
    st = d.wait_state()
    assert st["session"] == 0x12345678 and st["owner"] == 0, st   # CRC 不一致时 parse_state 返回 None，这里会超时
    r = d.get()
    want = dict(T.DEFAULTS)
    assert r["code"] == 0 and r["state"] == 0 and not r["telemetry"]
    for k, v in want.items():
        got = r["cfg"][k]
        assert (abs(got - v) < 1e-6 if isinstance(v, float) else got == v), (k, got, v)
    assert T.encode_cfg(r["cfg"]) == r["raw_cfg"], "Python 编码与固件默认参数字节不一致"
    sh.close()


def test_roundtrip_boundaries():
    sh, d = new_dev()
    base = d.get()["cfg"]
    cases = [{"sens": 1}, {"sens": 200}, {"sens": 28.37}, {"accel": 1}, {"accel": 4}, {"accel_lo": 0, "accel_hi": 2},
             {"accel_hi": 510}, {"accel_hi": 251}, {"deadzone": 0}, {"deadzone": 5}, {"deadzone": 0.7},
             {"smooth_lo": 0, "smooth_hi": 0}, {"smooth_hi": 255}, {"tau": 0}, {"tau": 200}, {"freeze": 0},
             {"freeze": 255}, {"invert_x": True}, {"invert_y": True}, {"gravity": False}]
    for c in cases:
        cfg = dict(base, **c)
        sent = T.encode_cfg(cfg)
        r = d.set_cfg(cfg)
        assert r["raw_cfg"] == sent, (c, sent.hex(), r["raw_cfg"].hex())
        assert T.encode_cfg(r["cfg"]) == sent, c
    for perm in itertools.permutations(range(3)):
        for neg in range(8):
            cfg = dict(base, axis_src=list(perm), axis_neg=neg)
            r = d.set_cfg(cfg)
            assert r["cfg"]["axis_src"] == list(perm) and r["cfg"]["axis_neg"] == neg
    sh.close()


def test_validity_matches_firmware():
    """随机字节直接发给固件：cfg_problems 的判定必须和 ak_pointer_cfg_valid 一致。"""
    rnd = random.Random(20261106)
    sh, d = new_dev()
    seen = {0: 0, 3: 0}
    good = T.encode_cfg(T.DEFAULTS)
    for i in range(4000):
        if i % 2:                       # 一半从合法参数改一个字节：贴着边界走
            b = bytearray(good)
            b[rnd.randrange(0, 14)] = rnd.randrange(256)
            if b[11] > 7: b[11] &= 7     # 保留位由另一条路径（帧/解码）拒绝，这里只比范围判定
            if b[13] > 7: b[13] &= 7
            if b[12] & 0xC0: b[12] &= 0x3F
        else:                           # 一半完全随机
            b = bytearray(16)
            b[0:2] = rnd.randrange(0, 65536).to_bytes(2, "little")
            b[2:4] = rnd.randrange(0, 65536).to_bytes(2, "little")
            for k in range(4, 11):
                b[k] = rnd.randrange(256)
            b[11] = rnd.randrange(8)
            src = rnd.choice([list(rnd.sample(range(3), 3)), [rnd.randrange(3) for _ in range(3)]])
            b[12] = src[0] | src[1] << 2 | src[2] << 4
            b[13] = rnd.randrange(8)
        r = d.request(T.OP_SET, bytes(b))
        expect = 3 if T.cfg_problems(T.decode_cfg(bytes(b))) else 0
        assert r["code"] == expect, (b.hex(), r["code"], T.cfg_problems(T.decode_cfg(bytes(b))))
        seen[r["code"]] += 1
        if r["code"] == 0:
            assert r["raw_cfg"] == bytes(b)
    assert seen[0] > 100 and seen[3] > 100, seen     # 两种结果都要真的覆盖到
    sh.close()


def test_errors_and_ops():
    sh, d = new_dev()
    d.wait_state()
    # 坏 CRC
    f = bytearray(T.build_frame(T.OP_GET, d.session, 7))
    f[30] ^= 0xFF
    d.tr.write(bytes([3]) + bytes(f))
    r = T.parse_reply(d.tr.read(10)[1:])
    assert r["code"] == 1, r
    # session 变化：自动重取
    assert sh.cmd("session abcd0001") == "OK"
    r = d.request(T.OP_GET)
    assert r["code"] == 0 and d.session == 0xABCD0001
    # 不重试时能看到 session 错
    assert sh.cmd("session abcd0002") == "OK"
    assert d.request(T.OP_GET, _retry=False)["code"] == 2
    d.wait_state()
    # 保存
    assert d.ok(T.OP_SAVE)["code"] == 0
    sh.cmd("savefail 1")
    try:
        d.ok(T.OP_SAVE)
        raise AssertionError("保存失败应报错")
    except T.E24Error as e:
        assert "保存失败" in str(e)
    sh.cmd("savefail 0")
    # 遥测
    assert d.telemetry(True)["telemetry"] and not d.telemetry(False)["telemetry"]
    assert d.request(T.OP_TEL, bytes([2]) + bytes(15))["code"] == 3
    # 下载模式口令
    assert d.request(T.OP_DFU, b"DFU?" + bytes(12))["code"] == 3
    assert d.request(T.OP_DFU, b"DFU!" + bytes(12))["code"] == 0
    # 恢复默认
    d.set_cfg(dict(d.get()["cfg"], sens=50))
    assert d.ok(T.OP_DEFAULTS)["cfg"]["sens"] == 28.0
    # 校准状态
    r = d.ok(T.OP_CAL)
    assert d.get()["state"] == 1
    assert sh.cmd("feed 0.3 -0.2 0.1 0 0 1 260").split()[3] == "2"
    assert d.get()["state"] == 2
    sh.close()


def test_derive_axes_errors():
    assert T.derive_axes([0, 0, 1], [0, 1, 0]) == ([0, 1, 2], 0)
    for a, b, word in (([0, 0, 1], [0, 0, -1], "同一个"), ([0.6, 0, 0.8], [0, 1, 0], "单一轴"),
                       ([0, 0, 0.5], [0, 1, 0], "1 g")):
        try:
            T.derive_axes(a, b)
            raise AssertionError((a, b))
        except ValueError as e:
            assert word in str(e), e


def proper_mounts():
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = [[0] * 3 for _ in range(3)]
            for i in range(3):
                m[perm[i]][i] = signs[i]
            det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                   - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                   + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
            if det == 1:
                yield m


def test_wizard_all_mountings():
    """24 种传感器安装方向：向导推导 → 写入固件 → 用真实 pointer.c 校准并转动 → 方向都对。"""
    real_time = T.time
    count = 0
    try:
        for m in proper_mounts():
            sh, d = new_dev()
            clock = FakeClock()
            T.time = clock
            tel = SimTelemetry(sh, clock, m)
            flat, nose = (0, 0, 1), (0, 1, 0)
            ui = ScriptUI([lambda: tel.pose(flat), lambda: tel.pose(nose), lambda: tel.pose(flat),
                           lambda: tel.pose(flat, (0, 0, -30)),    # 绕设备 -Z = 向右转
                           lambda: tel.pose(flat, (30, 0, 0))])    # 绕设备 +X = 前端上抬
            cfg = T.run_wizard(d, tel, ui, capture_s=0.3, move_s=1.0)
            src = [next(k for k in range(3) if m[k][i]) for i in range(3)]
            neg = sum((1 << i) for i in range(3) if m[src[i]][i] < 0)
            assert (cfg["axis_src"], cfg["axis_neg"]) == (src, neg), (m, cfg)
            text = "\n".join(ui.said)
            assert "方向核对通过" in text, text
            # 再独立核一次光标方向：看整数位移
            tel.pose(flat)
            tel.advance(0.5)
            tel.pose(flat, (0, 0, -30))
            yaw = [tel._feed(1) for _ in range(100)]
            assert sum(s["dx"] for s in yaw) > 100 and abs(sum(s["dy"] for s in yaw)) < 10, m
            tel.pose(flat)
            tel.advance(0.5)
            tel.pose(flat, (30, 0, 0))
            pitch = [tel._feed(1) for _ in range(100)]
            assert sum(s["dy"] for s in pitch) < -100, m
            sh.close()
            count += 1
    finally:
        T.time = real_time
    assert count == 24, count


def test_wizard_wrong_motion_reported():
    """用户转反了：向导必须说没通过，不能写“通过”。"""
    real_time = T.time
    try:
        sh, d = new_dev()
        clock = FakeClock()
        T.time = clock
        tel = SimTelemetry(sh, clock, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        flat, nose = (0, 0, 1), (0, 1, 0)
        ui = ScriptUI([lambda: tel.pose(flat), lambda: tel.pose(nose), lambda: tel.pose(flat),
                       lambda: tel.pose(flat, (0, 0, 30)), lambda: tel.pose(flat, (30, 0, 0))])
        T.run_wizard(d, tel, ui, capture_s=0.3, move_s=1.0)
        text = "\n".join(ui.said)
        assert "方向核对没通过" in text and "方向核对通过" not in text, text
        sh.close()
    finally:
        T.time = real_time


def test_wizard_shaking_retries():
    samples = [{"a": [0, 0, 1], "g": [(-1) ** i * 10, 0, 0]} for i in range(50)]
    assert not T.summarize_still(samples)["still"]
    samples = [{"a": [0, 0, 1], "g": [0.2, 0.1, -0.1]} for _ in range(50)]
    assert T.summarize_still(samples)["still"]


def test_tune_steps():
    sh, d = new_dev()
    c = d.get()["cfg"]
    c2, msg = T.tune_step(d, c, "]")
    assert abs(c2["sens"] - 30.8) < 1e-6 and "灵敏度" in msg
    c3, _ = T.tune_step(d, c2, "[")
    assert c3["sens"] < c2["sens"]
    assert T.tune_step(d, c, ",")[0]["deadzone"] == 0.6
    assert T.tune_step(d, c, "x")[0]["invert_x"] is True
    assert T.tune_step(d, c, "g")[0]["gravity"] is False
    c4 = d.set_cfg(dict(c, sens=199))["cfg"]
    c5, msg = T.tune_step(d, c4, "]")
    assert c5 == c4 and "边界" in msg
    c6 = d.set_cfg(dict(c, smooth_lo=4, smooth_hi=4))["cfg"]
    c7, msg = T.tune_step(d, c6, "9")
    assert c7 == c6 and "不能低于" in msg
    assert T.tune_step(d, c, "r")[0]["sens"] == 28.0
    assert "已保存" in T.tune_step(d, c, "s")[1]
    sh.close()


def test_tune_on_real_tty():
    """走真实 termios：pty 上按键 → 单键模式 → 固件参数变化 → 退出后终端恢复。"""
    import os
    import pty
    import termios
    import threading
    import time
    sh, d = new_dev()
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    old_in = sys.stdin
    sys.stdin = os.fdopen(slave, "r", closefd=False)

    def keys():
        time.sleep(0.3)                 # setcbreak 会清掉更早的输入
        os.write(master, b"]")
        time.sleep(0.1)
        os.write(master, b"q")

    th = threading.Thread(target=keys)
    th.start()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            T.run_tune(d)
    finally:
        th.join()
        sys.stdin = old_in
    assert abs(d.get()["cfg"]["sens"] - 30.8) < 1e-6
    mask = termios.ECHO | termios.ICANON    # macOS 恢复后内核会留 PENDIN 位，无害，只比关键模式
    assert termios.tcgetattr(slave)[3] & mask == before[3] & mask, "退出后终端模式没恢复"
    os.close(master)
    os.close(slave)
    sh.close()


def test_restore_defaults_keeps_axes():
    """向导结果不能被恢复默认清掉，校准也不能丢（经真实 C 代码）。"""
    sh, d = new_dev()
    c = d.set_cfg(dict(d.get()["cfg"], sens=60, tau=10, invert_x=True, axis_src=[1, 2, 0], axis_neg=5))["cfg"]
    assert sh.cmd("feed 0.3 -0.2 0.1 0 1 0 260").split()[3] == "2"
    c2, msg = T.tune_step(d, c, "r")
    assert "保留" in msg
    assert (c2["axis_src"], c2["axis_neg"]) == ([1, 2, 0], 5)
    assert c2["sens"] == 28.0 and c2["tau"] == 40.0 and c2["invert_x"] is False
    assert d.get()["state"] == 2, "恢复手感不该触发重新校准"
    assert d.ok(T.OP_DEFAULTS)["cfg"]["axis_src"] == [0, 1, 2]    # 固件 0x16 的行为，--axes 才用
    assert T.DEFAULTS["axis_src"] == [0, 1, 2], "不能改到默认表"
    sh.close()


def test_assignments():
    c = dict(T.DEFAULTS)
    n = T.apply_assignments(c, ["sens=32", "gravity=off", "axes=-y,+z,-x", "freeze=80"])
    assert n["sens"] == 32 and n["gravity"] is False and n["axis_src"] == [1, 2, 0] and n["axis_neg"] == 5 and n["freeze"] == 80
    assert c["sens"] == 28.0 and c["axis_src"] == [0, 1, 2], "不能改到原字典"
    assert T.axes_to_str(*T.axes_from_str("-y,+z,-x")) == "-y,+z,-x"
    for bad in (["nope=1"], ["sens"], ["axes=+x,+x,+z"], ["axes=+x,+y"], ["invert_x=2"]):
        try:
            T.apply_assignments(c, bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_cdc_parsing():
    """CDC 上日志和遥测混在一起：只取完整的 imu 行。"""
    class Ser:
        def __init__(self, data):
            self.d = data

        def read(self, n):
            c, self.d = self.d[:n], self.d[n:]
            return c

    imu = b'{"v":1,"type":"imu","t":5,"dt":0.005,"g":[0,0,0],"a":[0,0,1],"h":0,"vv":0,"dx":0,"dy":0,"bias":[0,0,0],"cal":2,"still":1}\n'
    raw = (b"I (123) link: \xe5\x90\xaf\xe5\x8a\xa8\n" + imu + b'{"v":1,"type":"imu","t":6,"g":[0,I (130) x: cut\n'
           + b'{"type":"other"}\n' + b"\xff\xfe garbage\n" + imu)
    t = T.CdcTelemetry.__new__(T.CdcTelemetry)
    logs = []
    t.ser, t._buf, t.on_log = Ser(raw), b"", logs.append
    got = [t.read(0.05), t.read(0.05), t.read(0.02)]
    assert got[0]["t"] == 5 and got[1]["t"] == 5 and got[2] is None, got
    assert any("启动" in x for x in logs), logs


def test_audio_status_decode():
    a = T.decode_audio(bytes([0x09, 99, 0, 0, 0x28, 0xEA, 0x10, 0xF2, 0x00, 0x7D, 0, 0, 1, 0, 2, 0]))
    assert a["clock"] and a["test_valid"] and not a["gate"] and not a["amp"] and not a["failed"]
    assert a["left_pct"] == 99 and a["right_pct"] == 0 and a["frames"] == 32000
    assert a["rms_db"] == -55.92 and a["peak_db"] == -35.68 and a["rx_errors"] == 1 and a["uac_overflow"] == 2
    assert "RMS -55.9" in T.fmt_audio(a)


def test_command_frame():
    b = T.build_command(T.CMD_RECORD, 0x11223344, 7, 1)
    assert len(b) == 32 and b[0] == 1 and b[1] == 5 and b[4:8] == bytes([0x44, 0x33, 0x22, 0x11])
    assert b[8] == 7 and b[16] == 1 and T.crc_ok(b) and not any(b[12:16]) and not any(b[17:30])


def test_tone_payload():
    b = T.encode_tone(1000, 200, 40)
    assert len(b) == 16 and b[:4] == b"SPK!" and b[4:9] == bytes([0xE8, 3, 0xC8, 0, 40]) and not any(b[9:])


def test_record_twice_same_session():
    """2026-11-16 上板发现：同一 session 里第二次 record 从序号 1 开始，HELLO/CLAIM 被判 STALE，接管静默失败。"""
    sh, dev = new_dev()
    real_time = T.time
    try:
        T.time = FakeClock()
        for run in range(2):
            dev.tr.cmd_results.clear()
            T.run_record(dev, 0.05, on_tick=lambda m: None)
            res = dev.tr.cmd_results
            assert res and res[0][0] == T.CMD_HELLO and res[1][0] == T.CMD_CLAIM, (run, res)
            assert all(code == 0 for _, code in res), f"第 {run + 1} 次 record 有命令被拒：{res}"
            assert res[-1][0] == T.CMD_RELEASE, (run, res)
        assert dev.wait_state()["cmd_seq"] > 0
    finally:
        T.time = real_time
        sh.close()


def test_cdc_baud_guard():
    assert T.CDC_BAUD == 115200


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
for t in TESTS:
    t()
    print("PASS", t.__name__)
print(f"{len(TESTS)} 项通过")
