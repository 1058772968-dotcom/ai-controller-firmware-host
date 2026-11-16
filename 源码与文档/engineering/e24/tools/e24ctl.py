#!/usr/bin/env python3
"""E24 固件侧调参小工具（联调档 link）。

经 USB HID 报告 3（配置通道）读写陀螺仪指向参数、重新校准、开关遥测；经 CDC 串口读 100 Hz 遥测，
做轴向向导、静置漂移检查和实时手感调节。

- 不需要上位机网页，也不需要 HELLO/CLAIM：配置通道只核对 session，普通鼠标模式下照样能调，光标边调边动。
- 以非独占方式打开 HID，不抢系统鼠标，也不挡上位机网页的 WebHID。
- 依赖：Homebrew 的 hidapi（libhidapi.dylib，ctypes 调用，不装 Python 包）；遥测相关命令另需 pyserial。
- 帧格式与固件 firmware/components/aikey_core/include/devcfg.h、pointer.h 一致；
  电脑端测试 tests/host/e24ctl_test.py 用固件同一份 C 代码做对端。

常用：
  python3 tools/e24ctl.py info
  python3 tools/e24ctl.py wizard        # 轴向向导
  python3 tools/e24ctl.py tune          # 单键实时调手感
  python3 tools/e24ctl.py set sens=32 deadzone=0.5
  python3 tools/e24ctl.py save
（不要加 -I：pyserial 装在用户目录，-I 会把它屏蔽。）
"""
import argparse
import csv
import ctypes
import ctypes.util
import json
import math
import random
import sys
import time
from typing import Callable, List, Optional, Tuple

VID, PID = 0xCAFE, 0x4031
REPORT_MOUSE, REPORT_STATE, REPORT_CFG = 1, 2, 3
OP_GET, OP_SET, OP_SAVE, OP_CAL, OP_TEL, OP_DFU, OP_DEFAULTS = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16
OP_AUDIO, OP_MIC_TEST, OP_TONE = 0x17, 0x18, 0x19
OP_NAMES = {OP_GET: "读参数", OP_SET: "写参数", OP_SAVE: "保存", OP_CAL: "校准", OP_TEL: "遥测开关",
            OP_DFU: "进下载模式", OP_DEFAULTS: "恢复默认", OP_AUDIO: "读音频状态", OP_MIC_TEST: "麦克风自检",
            OP_TONE: "提示音"}
RESULT_TEXT = {0: "成功", 1: "帧格式错误", 2: "session 不符", 3: "参数超出范围", 4: "保存失败（NVS）",
               5: "音频忙（录音、自检或播放中）", 6: "音频不可用"}
PTR_STATE = {0: "未校准", 1: "校准中", 2: "可用"}
OWNER = {0: "普通鼠标（POINTER）", 1: "上位机接管（HOST）"}
FAULTS = {1: "IMU", 2: "音频", 4: "触觉（本档未实现）"}
# 绝不能用 1200：固件把 1200 bps 的串口设置当作“重启进 ROM 下载模式”（usb_link.c on_line_coding）
CDC_BAUD = 115200
assert CDC_BAUD != 1200


class E24Error(Exception):
    pass


# ---------------------------------------------------------------- 帧与参数编码（与固件逐字节一致）

def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE：初值 0xFFFF，多项式 0x1021，同协议 v1 的 ak_crc16。"""
    c = 0xFFFF
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def _seal(b: bytearray) -> bytes:
    c = crc16(bytes(b[:30]))
    b[30], b[31] = c & 0xFF, c >> 8
    return bytes(b)


def build_frame(op: int, session: int, tx: int, payload: bytes = bytes(16)) -> bytes:
    if len(payload) != 16:
        raise ValueError("负载必须 16 字节")
    b = bytearray(32)
    b[0], b[1] = 1, op
    b[4:8] = (session & 0xFFFFFFFF).to_bytes(4, "little")
    b[8:12] = (tx & 0xFFFFFFFF).to_bytes(4, "little")
    b[12:28] = payload
    return _seal(b)


def crc_ok(b: bytes) -> bool:
    c = crc16(b[:30])
    return len(b) == 32 and b[30] == (c & 0xFF) and b[31] == (c >> 8)


def parse_state(b: bytes) -> Optional[dict]:
    """报告 2（不含报告号）。CRC 不对或版本不对返回 None。"""
    if len(b) != 32 or b[0] != 1 or not crc_ok(b):
        return None
    flags = b[16]
    return {"type": b[1], "owner": b[2], "buttons": b[3], "session": int.from_bytes(b[4:8], "little"),
            "flags": flags, "host_connected": bool(flags & 1), "calibrated": bool(flags & 32),
            "hid_buttons": b[18], "faults": b[19], "cmd_seq": int.from_bytes(b[24:28], "little")}


def parse_reply(b: bytes) -> dict:
    if len(b) != 32 or b[0] != 1 or not (b[1] & 0x80):
        raise E24Error("配置回复格式不对")
    if not crc_ok(b):
        raise E24Error("配置回复 CRC 错误")
    op = b[1] & 0x7F
    audio = op in (OP_AUDIO, OP_MIC_TEST, OP_TONE)
    return {"op": op, "code": b[2], "state": b[3], "session": int.from_bytes(b[4:8], "little"),
            "tx": int.from_bytes(b[8:12], "little"), "cfg": None if audio else decode_cfg(b[12:28]),
            "audio": decode_audio(b[12:28]) if audio else None, "raw_cfg": bytes(b[12:28]),
            "telemetry": bool(b[28] & 1)}


def decode_audio(b: bytes) -> dict:
    """16 字节音频状态，格式见 devcfg.h。"""
    f = b[0]
    return {"clock": bool(f & 1), "gate": bool(f & 2), "testing": bool(f & 4), "test_valid": bool(f & 8),
            "tone": bool(f & 16), "amp": bool(f & 32), "streaming": bool(f & 64), "failed": bool(f & 128),
            "left_pct": b[1], "right_pct": b[2],
            "rms_db": int.from_bytes(b[4:6], "little", signed=True) / 100,
            "peak_db": int.from_bytes(b[6:8], "little", signed=True) / 100,
            "frames": int.from_bytes(b[8:12], "little"), "rx_errors": int.from_bytes(b[12:14], "little"),
            "uac_overflow": int.from_bytes(b[14:16], "little")}


CMD_HELLO, CMD_CLAIM, CMD_KEEPALIVE, CMD_RELEASE, CMD_RECORD = 1, 2, 3, 4, 5
KEY_V = 4
FLAG_MIC_POWER, FLAG_MIC_READY = 2, 4


def build_command(command: int, session: int, seq: int, value: int = 0) -> bytes:
    """报告 2 控制帧（协议 v1），不含报告号。"""
    b = bytearray(32)
    b[0], b[1] = 1, command
    b[4:8] = session.to_bytes(4, "little")
    b[8:12] = seq.to_bytes(4, "little")
    b[16] = value
    return _seal(b)


def encode_tone(hz: int, ms: int, atten_db: int) -> bytes:
    return b"SPK!" + hz.to_bytes(2, "little") + ms.to_bytes(2, "little") + bytes([atten_db]) + bytes(7)


def fmt_audio(a: dict) -> str:
    on = [t for k, t in (("clock", "时钟运行"), ("gate", "闸门打开"), ("testing", "自检中"), ("tone", "播放中"),
                         ("amp", "功放开"), ("streaming", "主机在收流"), ("failed", "故障")) if a[k]]
    lines = ["状态 " + ("、".join(on) if on else "空闲（时钟停、功放关）")]
    if a["test_valid"]:
        lines.append(f"自检 {a['frames']} 帧  RMS {a['rms_db']:.1f} dBFS  峰值 {a['peak_db']:.1f} dBFS  "
                     f"左槽非零 {a['left_pct']}%  右槽非零 {a['right_pct']}%")
    lines.append(f"I2S 读错误 {a['rx_errors']}  UAC 溢出 {a['uac_overflow']}")
    return "\n".join(lines)


# 参数：(键, 中文名, 单位)
PARAMS = [
    ("sens", "灵敏度", "计数/°"), ("accel", "加速倍率", "×"), ("accel_lo", "加速起点", "°/s"),
    ("accel_hi", "加速满点", "°/s"), ("deadzone", "软死区", "°/s"), ("smooth_lo", "全量平滑以下", "°/s"),
    ("smooth_hi", "平滑截止", "°/s"), ("tau", "平滑时间常数", "ms"), ("freeze", "点击冻结", "ms"),
    ("invert_x", "左右反转", ""), ("invert_y", "上下反转", ""), ("gravity", "重力补偿", ""),
    ("axes", "轴映射", ""),
]
DEFAULTS = {"sens": 28.0, "accel": 1.8, "accel_lo": 30.0, "accel_hi": 250.0, "deadzone": 0.7, "smooth_lo": 4.0,
            "smooth_hi": 15.0, "tau": 40.0, "freeze": 70, "invert_x": False, "invert_y": False, "gravity": True,
            "axis_src": [0, 1, 2], "axis_neg": 0}


def _q(v: float, scale: float, hi: int) -> int:
    x = v * scale + 0.5          # 同固件 q8/q16：四舍五入后截断到范围
    return int(min(max(x, 0.0), float(hi)))


def encode_cfg(c: dict) -> bytes:
    o = bytearray(16)
    o[0:2] = _q(c["sens"], 100, 65535).to_bytes(2, "little")
    o[2:4] = _q(c["accel"], 100, 65535).to_bytes(2, "little")
    o[4] = _q(c["accel_lo"], 1, 255)
    o[5] = _q(c["accel_hi"], 0.5, 255)
    o[6] = _q(c["deadzone"], 10, 255)
    o[7] = _q(c["smooth_lo"], 1, 255)
    o[8] = _q(c["smooth_hi"], 1, 255)
    o[9] = _q(c["tau"], 1, 255)
    o[10] = min(int(c["freeze"]), 255)
    o[11] = (1 if c["invert_x"] else 0) | (2 if c["invert_y"] else 0) | (4 if c["gravity"] else 0)
    s = c["axis_src"]
    o[12] = s[0] | s[1] << 2 | s[2] << 4
    o[13] = c["axis_neg"]
    return bytes(o)


def decode_cfg(b: bytes) -> dict:
    return {"sens": int.from_bytes(b[0:2], "little") / 100.0, "accel": int.from_bytes(b[2:4], "little") / 100.0,
            "accel_lo": float(b[4]), "accel_hi": b[5] * 2.0, "deadzone": b[6] / 10.0, "smooth_lo": float(b[7]),
            "smooth_hi": float(b[8]), "tau": float(b[9]), "freeze": b[10], "invert_x": bool(b[11] & 1),
            "invert_y": bool(b[11] & 2), "gravity": bool(b[11] & 4),
            "axis_src": [b[12] & 3, (b[12] >> 2) & 3, (b[12] >> 4) & 3], "axis_neg": b[13]}


def cfg_problems(c: dict) -> List[str]:
    """与固件 ak_pointer_cfg_valid 相同的范围（固件是最终裁判，这里只为提前给出中文提示）。"""
    p = []
    if not 1.0 <= c["sens"] <= 200.0: p.append("灵敏度需在 1–200")
    if not 1.0 <= c["accel"] <= 4.0: p.append("加速倍率需在 1–4")
    if not (c["accel_lo"] >= 0 and c["accel_lo"] < c["accel_hi"] <= 510): p.append("加速起点需小于满点，满点 ≤ 510")
    if not 0 <= c["deadzone"] <= 5: p.append("软死区需在 0–5")
    if not (c["smooth_lo"] >= 0 and c["smooth_lo"] <= c["smooth_hi"] <= 255): p.append("平滑区间需 0 ≤ 下限 ≤ 截止 ≤ 255")
    if not 0 <= c["tau"] <= 200: p.append("平滑时间常数需在 0–200 ms")
    if not 0 <= c["freeze"] <= 255: p.append("点击冻结需在 0–255 ms")
    if sorted(c["axis_src"]) != [0, 1, 2] or not 0 <= c["axis_neg"] <= 7: p.append("轴映射需是 x/y/z 的一个排列")
    return p


def axes_to_str(src: List[int], neg: int) -> str:
    return ",".join(("-" if (neg >> i) & 1 else "+") + "xyz"[src[i]] for i in range(3))


def axes_from_str(s: str) -> Tuple[List[int], int]:
    """“+x,+y,+z” 依次表示设备 X/Y/Z 取自传感器哪一轴、是否取反。"""
    parts = [p.strip().lower() for p in s.split(",")]
    if len(parts) != 3:
        raise ValueError("轴映射写法如 +x,+y,+z 或 -y,+z,-x")
    src, neg = [], 0
    for i, p in enumerate(parts):
        sign = p[0] if p and p[0] in "+-" else "+"
        name = p[1:] if p and p[0] in "+-" else p
        if name not in ("x", "y", "z"):
            raise ValueError(f"看不懂“{p}”，轴只能是 x/y/z")
        src.append("xyz".index(name))
        if sign == "-":
            neg |= 1 << i
    if sorted(src) != [0, 1, 2]:
        raise ValueError("三个设备轴必须各取不同的传感器轴")
    return src, neg


def apply_assignments(c: dict, items: List[str]) -> dict:
    c = dict(c)
    c["axis_src"] = list(c["axis_src"])
    keys = {k for k, _, _ in PARAMS}
    for it in items:
        if "=" not in it:
            raise ValueError(f"“{it}”应写成 键=值")
        k, v = (x.strip() for x in it.split("=", 1))
        if k not in keys:
            raise ValueError(f"没有参数“{k}”，可用：{', '.join(sorted(keys))}")
        if k == "axes":
            c["axis_src"], c["axis_neg"] = axes_from_str(v)
        elif k in ("invert_x", "invert_y", "gravity"):
            if v.lower() not in ("0", "1", "on", "off", "true", "false"):
                raise ValueError(f"{k} 只能是 0/1")
            c[k] = v.lower() in ("1", "on", "true")
        elif k == "freeze":
            c[k] = int(float(v))
        else:
            c[k] = float(v)
    return c


def defaults_keeping_axes(c: dict) -> dict:
    """默认手感参数 + 当前轴映射。固件 0x16 会连轴映射一起重置，轴向向导的结果就丢了，还要重新校准。"""
    return dict(DEFAULTS, axis_src=list(c["axis_src"]), axis_neg=c["axis_neg"])


def fmt_cfg(c: dict) -> str:
    rows = []
    for k, name, unit in PARAMS:
        if k == "axes":
            v = axes_to_str(c["axis_src"], c["axis_neg"])
        elif k in ("invert_x", "invert_y", "gravity"):
            v = "开" if c[k] else "关"
        elif k == "freeze":
            v = str(c[k])
        else:
            v = f"{c[k]:g}"
        rows.append(f"  {name:<8}{k:<10} {v} {unit}".rstrip())
    return "\n".join(rows)


# ---------------------------------------------------------------- 轴向推导

def cross(a: List[float], b: List[float]) -> List[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dominant_axis(a: List[float], what: str) -> Tuple[int, int]:
    n = math.sqrt(sum(x * x for x in a))
    if not 0.8 <= n <= 1.2:
        raise ValueError(f"{what}：加速度合计 {n:.2f} g，不像静止（应约 1 g）")
    i = max(range(3), key=lambda k: abs(a[k]))
    rest = max(abs(a[k]) for k in range(3) if k != i)
    if abs(a[i]) < 0.85 or rest > 0.4:
        raise ValueError(f"{what}：重力没有落在单一轴上（{a[0]:+.2f}, {a[1]:+.2f}, {a[2]:+.2f} g），请摆正后重来")
    return i, (1 if a[i] > 0 else -1)


def derive_axes(a_flat: List[float], a_nose_up: List[float]) -> Tuple[List[int], int]:
    """a_flat：正面朝上平放时的传感器加速度（设备 +Z 朝上）；
    a_nose_up：前端（指向屏幕那头）竖直朝上时的加速度（设备 +Y 朝上）。
    静止时朝上的轴读 +1 g。设备 X 由右手系 X = Y × Z 得出。"""
    zi, zs = dominant_axis(a_flat, "平放")
    yi, ys = dominant_axis(a_nose_up, "竖起")
    if zi == yi:
        raise ValueError("两次姿势的重力落在同一个传感器轴上：竖起那一步要让前端朝天花板")
    ez, ey = [0, 0, 0], [0, 0, 0]
    ez[zi], ey[yi] = zs, ys
    ex = cross(ey, ez)
    xi = next(k for k in range(3) if ex[k])
    src = [xi, yi, zi]
    neg = (1 if ex[xi] < 0 else 0) | (2 if ys < 0 else 0) | (4 if zs < 0 else 0)
    return src, neg


# ---------------------------------------------------------------- 传输层

class HidapiTransport:
    """ctypes 调 Homebrew 的 libhidapi。read 返回带报告号的字节串。"""

    def __init__(self, path: Optional[bytes] = None):
        self.lib = _load_hidapi()
        if self.lib.hid_init() != 0:
            raise E24Error("hidapi 初始化失败")
        if hasattr(self.lib, "hid_darwin_set_open_exclusive"):
            self.lib.hid_darwin_set_open_exclusive(0)   # 默认独占会让系统鼠标停住
        if path is None:
            ents = enumerate_hid()
            if not ents:
                raise E24Error("没找到 E24（VID 0xCAFE / PID 0x4031）。确认烧的是联调档（link），并已插好 USB；"
                               "点亮档（bringup）没有 HID。")
            vend = [e for e in ents if e["usage_page"] == 0xFF00] or ents
            path = vend[0]["path"]
        self.dev = self.lib.hid_open_path(path)
        if not self.dev:
            raise E24Error("打不开 E24 的 HID 接口。macOS 上请到 系统设置 → 隐私与安全性 → 输入监控，"
                           "给当前终端 App 打勾后重开终端；另外确认没有别的程序独占打开它。")
        self._buf = (ctypes.c_ubyte * 65)()

    def write(self, data: bytes) -> None:
        b = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        if self.lib.hid_write(self.dev, b, len(data)) < 0:
            raise E24Error(f"HID 写失败：{self.lib.hid_error(self.dev) or '未知'}")

    def read(self, timeout_ms: int) -> Optional[bytes]:
        n = self.lib.hid_read_timeout(self.dev, self._buf, 65, int(timeout_ms))
        if n < 0:
            raise E24Error("HID 读失败（设备可能已拔出或重启）")
        return bytes(self._buf[:n]) if n else None

    def close(self) -> None:
        if self.dev:
            self.lib.hid_close(self.dev)
            self.dev = None


class _HidInfo(ctypes.Structure):
    pass


_HidInfo._fields_ = [("path", ctypes.c_char_p), ("vendor_id", ctypes.c_ushort), ("product_id", ctypes.c_ushort),
                     ("serial_number", ctypes.c_wchar_p), ("release_number", ctypes.c_ushort),
                     ("manufacturer_string", ctypes.c_wchar_p), ("product_string", ctypes.c_wchar_p),
                     ("usage_page", ctypes.c_ushort), ("usage", ctypes.c_ushort), ("interface_number", ctypes.c_int),
                     ("next", ctypes.POINTER(_HidInfo)), ("bus_type", ctypes.c_int)]
_LIB = None


def _load_hidapi():
    global _LIB
    if _LIB:
        return _LIB
    cands = [ctypes.util.find_library("hidapi"), "/opt/homebrew/lib/libhidapi.dylib", "/usr/local/lib/libhidapi.dylib"]
    for c in cands:
        if not c:
            continue
        try:
            lib = ctypes.CDLL(c)
            break
        except OSError:
            continue
    else:
        raise E24Error("找不到 libhidapi。请先运行：brew install hidapi")
    vp, us, buf = ctypes.c_void_p, ctypes.c_ushort, ctypes.POINTER(ctypes.c_ubyte)
    lib.hid_init.restype = ctypes.c_int
    lib.hid_enumerate.argtypes, lib.hid_enumerate.restype = [us, us], ctypes.POINTER(_HidInfo)
    lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_HidInfo)]
    lib.hid_open_path.argtypes, lib.hid_open_path.restype = [ctypes.c_char_p], vp
    lib.hid_write.argtypes, lib.hid_write.restype = [vp, buf, ctypes.c_size_t], ctypes.c_int
    lib.hid_read_timeout.argtypes, lib.hid_read_timeout.restype = [vp, buf, ctypes.c_size_t, ctypes.c_int], ctypes.c_int
    lib.hid_close.argtypes = [vp]
    lib.hid_error.argtypes, lib.hid_error.restype = [vp], ctypes.c_wchar_p
    if hasattr(lib, "hid_darwin_set_open_exclusive"):
        lib.hid_darwin_set_open_exclusive.argtypes = [ctypes.c_int]
    _LIB = lib
    return lib


def enumerate_hid() -> List[dict]:
    lib = _load_hidapi()
    head = lib.hid_enumerate(VID, PID)
    out, p = [], head
    while p:
        e = p.contents
        out.append({"path": e.path, "usage_page": e.usage_page, "usage": e.usage, "product": e.product_string,
                    "serial": e.serial_number, "release": e.release_number, "interface": e.interface_number})
        p = e.next
    if head:
        lib.hid_free_enumeration(head)
    return out


# ---------------------------------------------------------------- 设备会话

class E24:
    def __init__(self, transport, log: Callable[[str], None] = print):
        self.tr = transport
        self.log = log
        self.session: Optional[int] = None
        self.last_state: Optional[dict] = None
        self.tx = random.getrandbits(31)

    def _handle(self, data: bytes) -> Optional[dict]:
        """处理一条输入报告；若是配置回复则返回解析结果。"""
        if not data:
            return None
        rid, body = data[0], data[1:]
        if rid == REPORT_STATE:
            st = parse_state(body[:32])
            if st:
                self.last_state = st
                self.session = st["session"]
        elif rid == REPORT_CFG and len(body) >= 32:
            return parse_reply(body[:32])
        return None

    def wait_state(self, timeout: float = 1.5) -> dict:
        end = time.monotonic() + timeout
        self.last_state = None
        while time.monotonic() < end:
            self._handle(self.tr.read(50) or b"")
            if self.last_state:
                return self.last_state
        raise E24Error("1.5 秒内没收到状态报告：确认烧的是联调档；macOS 上检查 输入监控 权限。")

    def request(self, op: int, payload: bytes = bytes(16), timeout: float = 0.8, _retry: bool = True) -> dict:
        if self.session is None:
            self.wait_state()
        self.tx = (self.tx + 1) & 0xFFFFFFFF
        frame = build_frame(op, self.session, self.tx, payload)
        self.tr.write(bytes([REPORT_CFG]) + frame)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r = self._handle(self.tr.read(50) or b"")
            if r and r["op"] == op and r["tx"] == self.tx:
                if r["code"] == 2 and _retry:          # USB 重连后 session 会换：重取一次再发
                    self.session = None
                    return self.request(op, payload, timeout, _retry=False)
                return r
        raise E24Error(f"{OP_NAMES.get(op, hex(op))}：{timeout:.1f} 秒内没有回复")

    def ok(self, op: int, payload: bytes = bytes(16)) -> dict:
        r = self.request(op, payload)
        if r["code"]:
            raise E24Error(f"{OP_NAMES.get(op, hex(op))}失败：{RESULT_TEXT.get(r['code'], r['code'])}")
        return r

    def get(self) -> dict:
        return self.ok(OP_GET)

    def set_cfg(self, c: dict) -> dict:
        probs = cfg_problems(c)
        if probs:
            raise E24Error("；".join(probs))
        return self.ok(OP_SET, encode_cfg(c))

    def telemetry(self, on: bool) -> dict:
        return self.ok(OP_TEL, bytes([1 if on else 0]) + bytes(15))

    def wait_calibrated(self, timeout: float = 8.0, on_tick: Optional[Callable[[dict], None]] = None) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r = self.get()
            if on_tick:
                on_tick(r)
            if r["state"] == 2:
                return True
            time.sleep(0.2)
        return False


# ---------------------------------------------------------------- CDC 遥测

class CdcTelemetry:
    """读 CDC 口的 JSON 行。固件日志和遥测混在一起，只取能解析的 type=imu 行，日志行交给 on_log。"""

    def __init__(self, port: Optional[str] = None, on_log: Optional[Callable[[str], None]] = None):
        try:
            import serial  # noqa: F401
            from serial.tools import list_ports
        except ImportError:
            raise E24Error("遥测需要 pyserial：python3 -m pip install --user pyserial")
        if port is None:
            ports = [p.device for p in list_ports.comports() if p.vid == VID and p.pid == PID]
            if not ports:
                raise E24Error("没找到 E24 的 CDC 串口（按 VID/PID 找）。可用 --port 指定 /dev/cu.usbmodemXXXX。")
            port = sorted(ports)[0]
        import serial
        self.port = port
        self.on_log = on_log
        self.ser = serial.Serial(port, CDC_BAUD, timeout=0.05)
        self.ser.dtr = True          # 固件只在 DTR 置位时发遥测
        self._buf = b""

    def flush(self) -> None:
        self.ser.reset_input_buffer()
        self._buf = b""

    def read(self, timeout: float = 0.2) -> Optional[dict]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            nl = self._buf.find(b"\n")
            if nl < 0:
                chunk = self.ser.read(512)
                if chunk:
                    self._buf += chunk
                continue
            line, self._buf = self._buf[:nl].strip(), self._buf[nl + 1:]
            if line.startswith(b"{"):
                try:
                    d = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue          # 日志把一行遥测截断了：丢掉
                if isinstance(d, dict) and d.get("type") == "imu":
                    return d
            elif line and self.on_log:
                self.on_log(line.decode("utf-8", "replace"))
        return None

    def close(self) -> None:
        self.ser.close()


def collect(tel, seconds: float) -> List[dict]:
    out, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        d = tel.read(0.2)
        if d:
            out.append(d)
    return out


def summarize_still(samples: List[dict]) -> dict:
    """静置窗口：平均加速度、陀螺抖动、是否静止。"""
    if len(samples) < 20:
        raise ValueError("遥测样本太少（确认遥测已开、CDC 口没被别的程序占用）")
    a = [sum(s["a"][i] for s in samples) / len(samples) for i in range(3)]
    spread = max(max(s["g"][i] for s in samples) - min(s["g"][i] for s in samples) for i in range(3))
    return {"a": a, "gyro_spread": spread, "n": len(samples), "still": spread < 4.0}


def integrate(samples: List[dict], key: str) -> float:
    """把遥测里的角速度（°/s）对时间积分成角度（°）。"""
    tot = 0.0
    for prev, cur in zip(samples, samples[1:]):
        dt = (cur["t"] - prev["t"]) / 1000.0
        if 0 < dt < 0.1:
            tot += cur[key] * dt
    return tot


# ---------------------------------------------------------------- 交互流程

class Console:
    def say(self, msg: str) -> None:
        print(msg, flush=True)

    def wait_enter(self, msg: str) -> None:
        input(msg + "  [回车继续] ")

    def confirm(self, msg: str) -> bool:
        return input(msg + " [y/N] ").strip().lower() in ("y", "yes")


def run_wizard(dev: E24, tel, ui, capture_s: float = 1.0, move_s: float = 2.5) -> Optional[dict]:
    """轴向向导：两个静止姿势定轴 → 写入 → 等重新校准 → 转动核对方向。返回写入后的参数。"""
    cur = dev.get()["cfg"]
    dev.telemetry(True)

    def still_pose(prompt: str, what: str) -> List[float]:
        for _ in range(3):
            ui.wait_enter(prompt)
            tel.flush()
            s = summarize_still(collect(tel, capture_s))
            if s["still"]:
                return s["a"]
            ui.say(f"  {what}时检测到晃动（陀螺波动 {s['gyro_spread']:.1f} °/s），再来一次。")
        raise E24Error(f"{what}三次都没静止下来，向导中止")

    ui.say("第 1 步：正面（按键那面）朝上，平放在桌面上，前端指向屏幕。")
    a_flat = still_pose("  放好后别碰它", "平放")
    ui.say("第 2 步：把前端（指向屏幕那头）竖直朝向天花板，拿稳。")
    a_up = still_pose("  竖好后保持不动", "竖起")
    src, neg = derive_axes(a_flat, a_up)
    ui.say(f"  推导轴映射：{axes_to_str(src, neg)}（原来 {axes_to_str(cur['axis_src'], cur['axis_neg'])}）")

    # 先放好再写入：写入后设备一静止就开始校准，不能让它在手里校准
    ui.say("第 3 步：写入轴映射后要重新校准零偏。请先平放到桌面上。")
    ui.wait_enter("  放好后别碰它，回车后写入并校准约 2 秒")
    new = dict(cur, axis_src=src, axis_neg=neg, invert_x=False, invert_y=False)
    applied = dev.set_cfg(new)["cfg"]
    if not dev.wait_calibrated(8.0):
        raise E24Error("8 秒内没完成校准：确认设备是静止的，再运行 e24ctl.py cal")

    checks = []
    for prompt, key, want, label in (
        ("第 4 步：拿起来，按平常握法，水平向右转约 30°（像手电筒从左扫到右）", "h", 1, "向右转 → 光标向右"),
        ("第 5 步：回到中间，把前端向上抬约 30°", "vv", -1, "向上抬 → 光标向上"),
    ):
        ui.wait_enter(prompt + "；准备好后回车，然后在 2 秒内做完")
        tel.flush()
        ang = integrate(collect(tel, move_s), key)
        good = ang * want > 8.0
        checks.append(good)
        ui.say(f"  {label}：测得 {ang:+.1f}°，{'正确' if good else '不对'}")
    if all(checks):
        ui.say("方向核对通过。参数还没保存；确认手感后运行 save（或在 tune 里按 s）。")
    else:
        ui.say("方向核对没通过：多半是动作做反了或幅度太小，可再跑一次向导；"
               "如果平放、竖起两步做对了仍反，请把遥测记录（watch --csv）发给我。")
    return applied


TUNE_KEYS = [
    ("[", "]", "sens", "灵敏度", lambda v, d: v * (0.9 if d < 0 else 1.1)),
    ("-", "=", "accel", "加速倍率", lambda v, d: v + 0.1 * d),
    (",", ".", "deadzone", "软死区", lambda v, d: v + 0.1 * d),
    (";", "'", "tau", "平滑时间常数", lambda v, d: v + 5 * d),
    ("9", "0", "smooth_hi", "平滑截止", lambda v, d: v + 1 * d),
    ("{", "}", "freeze", "点击冻结", lambda v, d: v + 10 * d),
]
TUNE_HELP = ("按键：[ ] 灵敏度  - = 加速倍率  , . 死区  ; ' 平滑τ  9 0 平滑截止  { } 点击冻结\n"
             "      x 左右反转  y 上下反转  g 重力补偿  c 重新校准  r 恢复默认（保留轴向）  s 保存  h 帮助  q 退出")


def tune_step(dev: E24, cfg: dict, key: str) -> Tuple[dict, str]:
    """单键调节一步，返回（设备回读的参数, 提示）。纯逻辑，便于测试。"""
    for dn, up, k, name, f in TUNE_KEYS:
        if key in (dn, up):
            nxt = dict(cfg)
            v = f(cfg[k], -1 if key == dn else 1)
            nxt[k] = int(round(v)) if k == "freeze" else round(v, 2)
            if k == "smooth_hi" and nxt[k] < nxt["smooth_lo"]:
                return cfg, "平滑截止不能低于全量平滑下限"
            if cfg_problems(nxt):
                return cfg, f"{name}已到边界"
            r = dev.set_cfg(nxt)["cfg"]
            return r, f"{name} → {r[k]:g}"
    if key in ("x", "y", "g"):
        k = {"x": "invert_x", "y": "invert_y", "g": "gravity"}[key]
        r = dev.set_cfg(dict(cfg, **{k: not cfg[k]}))["cfg"]
        return r, f"{dict((p[0], p[1]) for p in PARAMS)[k]} → {'开' if r[k] else '关'}"
    if key == "c":
        dev.ok(OP_CAL)
        return cfg, "开始校准：请静置约 1.2 秒"
    if key == "r":
        return dev.set_cfg(defaults_keeping_axes(cfg))["cfg"], "已恢复默认手感，轴向保留（未保存）"
    if key == "s":
        return dev.ok(OP_SAVE)["cfg"], "已保存到设备（断电保留）"
    return cfg, ""


def run_record(dev: E24, seconds: float, on_tick: Callable[[str], None] = print) -> dict:
    """接管指针，按住 V 时请求录音，到时交还。录音文件由调用方另外开 ffmpeg 采。
    只有实体 V 键按住才可能开闸，这里绕不过去。"""
    st = dev.wait_state()
    # 固件只收比上一条更新的序号（controller.c newer()），交还后 session 不一定换；
    # 从 1 重新编号时第二次 record 的 HELLO/CLAIM 会被当成旧命令丢掉，闸门永远打不开
    session, seq = st["session"], (st["cmd_seq"] + 1) & 0xFFFFFFFF

    def send(cmd: int, value: int = 0) -> None:
        nonlocal seq
        dev.tr.write(bytes([REPORT_STATE]) + build_command(cmd, session, seq, value))
        seq += 1

    t0 = time.monotonic()
    log = {"v_down": [], "ready": [], "off": []}
    try:
        send(CMD_HELLO)
        time.sleep(0.05)
        send(CMD_CLAIM)
        last_keep, want, ready = time.monotonic(), False, False
        while time.monotonic() - t0 < seconds:
            now = time.monotonic()
            if now - last_keep >= 0.2:
                send(CMD_KEEPALIVE)
                last_keep = now
            data = dev.tr.read(20)
            r = parse_state(data[1:]) if data and data[0] == REPORT_STATE else None
            if not r or r["session"] != session:
                continue
            v = bool(r["buttons"] & KEY_V)
            if v and not want:
                want = True
                log["v_down"].append(now - t0)
                on_tick(f"{now - t0:.2f} s  V 按下，请求录音")
                send(CMD_RECORD, 1)
            elif not v and want:
                want = False
                log["off"].append(now - t0)
                on_tick(f"{now - t0:.2f} s  V 松开")
            is_ready = bool(r["flags"] & FLAG_MIC_READY)
            if is_ready and not ready:
                log["ready"].append(now - t0)
                on_tick(f"{now - t0:.2f} s  闸门打开")
            ready = is_ready
    finally:
        send(CMD_RELEASE)
    return log


def run_tune(dev: E24) -> None:
    import termios
    import tty
    cfg = dev.get()["cfg"]
    saved = dict(cfg)
    print(TUNE_HELP)
    print(fmt_cfg(cfg))
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            k = sys.stdin.read(1)
            if k == "q":
                break
            if k == "h":
                print("\n" + TUNE_HELP + "\n" + fmt_cfg(cfg))
                continue
            try:
                cfg, msg = tune_step(dev, cfg, k)
            except E24Error as e:
                msg = f"出错：{e}"
            if k == "s":
                saved = dict(cfg)
            if msg:
                dirty = "" if cfg == saved else "（未保存）"
                print(f"\r{msg}{dirty}" + " " * 10, flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if cfg != saved:
        print("注意：有改动没保存，断电会丢；需要保留就运行 e24ctl.py save")


def run_still(dev: E24, tel, ui, seconds: float) -> dict:
    dev.telemetry(True)
    ui.wait_enter("把设备平放在桌面上，别碰")
    if not dev.wait_calibrated(8.0):
        raise E24Error("8 秒内没完成校准")
    tel.flush()
    ui.say(f"记录 {seconds:g} 秒……")
    s = collect(tel, seconds)
    if len(s) < 10:
        raise E24Error("遥测样本太少")
    sens = dev.get()["cfg"]["sens"]
    h, v = integrate(s, "h"), integrate(s, "vv")
    still_ratio = sum(x["still"] for x in s) / len(s)
    b0, b1 = s[0]["bias"], s[-1]["bias"]
    res = {"samples": len(s), "drift_deg": [h, v], "drift_counts_est": [h * sens, v * sens],
           "still_ratio": still_ratio, "bias_start": b0, "bias_end": b1}
    ui.say(f"  漂移：水平 {h:+.3f}°，竖直 {v:+.3f}°（约 {h * sens:+.0f} / {v * sens:+.0f} 像素）")
    ui.say(f"  判定静止的时间占比 {still_ratio * 100:.0f}%；零偏 {b0} → {b1} °/s")
    ui.say("  参考：仿真里静置 10 秒漂移为 0；实测超过约 2 像素/10 秒再考虑加大死区。")
    return res


def run_watch(tel, seconds: Optional[float], csv_path: Optional[str]) -> None:
    w = None
    f = open(csv_path, "w", newline="") if csv_path else None
    if f:
        w = csv.writer(f)
        w.writerow(["t", "dt", "gx", "gy", "gz", "ax", "ay", "az", "h", "vv", "dx", "dy", "bx", "by", "bz", "cal", "still"])
    end = time.monotonic() + seconds if seconds else None
    last = 0.0
    try:
        while end is None or time.monotonic() < end:
            d = tel.read(0.2)
            if not d:
                continue
            if w:
                w.writerow([d["t"], d["dt"], *d["g"], *d["a"], d["h"], d["vv"], d["dx"], d["dy"], *d["bias"],
                            d["cal"], d["still"]])
            if time.monotonic() - last > 0.1:
                last = time.monotonic()
                g, a = d["g"], d["a"]
                print(f"\r{PTR_STATE.get(d['cal'], d['cal'])} {'静' if d['still'] else '动'}  "
                      f"水平{d['h']:+7.1f} 竖直{d['vv']:+7.1f} °/s  "
                      f"陀螺[{g[0]:+6.1f} {g[1]:+6.1f} {g[2]:+6.1f}]  加速[{a[0]:+.2f} {a[1]:+.2f} {a[2]:+.2f}]   ",
                      end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        print()
        if f:
            f.close()
            print(f"已写入 {csv_path}")


# ---------------------------------------------------------------- 命令行

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="E24 联调档调参小工具（HID 报告 3 + CDC 遥测）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="不需要上位机网页，也不抢系统鼠标；改动默认只在内存里，save 才写入设备。")
    ap.add_argument("--port", help="CDC 串口（默认按 VID/PID 自动找）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出找到的 HID 接口和 CDC 串口")
    sub.add_parser("info", help="状态报告 + 当前参数")
    sub.add_parser("get", help="读当前参数")
    p = sub.add_parser("set", help="写参数（立即生效，不保存），如 set sens=32 deadzone=0.5 axes=-y,+x,+z")
    p.add_argument("items", nargs="+")
    sub.add_parser("save", help="把当前参数保存到设备（断电保留）")
    p = sub.add_parser("defaults", help="恢复默认手感参数，保留轴映射（不保存）")
    p.add_argument("--axes", action="store_true", help="连轴映射一起恢复（要重新跑向导或校准）")
    sub.add_parser("cal", help="重新校准零偏（静置约 1.2 秒）")
    p = sub.add_parser("tel", help="开关 CDC 遥测")
    p.add_argument("state", choices=["on", "off"])
    p = sub.add_parser("watch", help="实时显示遥测，可存 CSV")
    p.add_argument("-s", "--seconds", type=float)
    p.add_argument("--csv")
    p.add_argument("--log", action="store_true", help="同时显示固件日志行")
    sub.add_parser("wizard", help="轴向向导")
    sub.add_parser("tune", help="单键实时调手感")
    p = sub.add_parser("still", help="静置漂移检查")
    p.add_argument("-s", "--seconds", type=float, default=10.0)
    sub.add_parser("dfu", help="重启进 ROM 下载模式（未实测）")
    sub.add_parser("audio", help="读音频状态")
    sub.add_parser("mic", help="麦克风电平自检约 1 秒：只回统计值，不传波形")
    p = sub.add_parser("record", help="接管指针若干秒：按住 V 时才录音（配合系统录音软件）")
    p.add_argument("-s", "--seconds", type=float, default=15)
    p = sub.add_parser("tone", help="播一次提示音（会出声；扬声器未冻结，音量上限 -30 dB）")
    p.add_argument("--hz", type=int, default=1000)
    p.add_argument("--ms", type=int, default=200)
    p.add_argument("--atten", type=int, default=40, help="比满幅低多少 dB，30 到 80")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for e in enumerate_hid():
            print(f"HID  usage_page=0x{e['usage_page']:04X} usage=0x{e['usage']:02X}  {e['product']}  "
                  f"序列号 {e['serial']}  bcdDevice 0x{e['release']:04X}")
        try:
            from serial.tools import list_ports
            for p in list_ports.comports():
                if p.vid == VID and p.pid == PID:
                    print(f"CDC  {p.device}")
        except ImportError:
            print("（未装 pyserial，跳过串口）")
        return 0

    tr = dev = tel = None
    try:
        tr = HidapiTransport()
        dev = E24(tr)
        if a.cmd == "info":
            st = dev.wait_state()
            r = dev.get()
            faults = [n for b, n in FAULTS.items() if st["faults"] & b] or ["无"]
            print(f"session 0x{st['session']:08X}  控制权 {OWNER.get(st['owner'], st['owner'])}  "
                  f"上位机{'已连接' if st['host_connected'] else '未连接'}")
            print(f"指向 {PTR_STATE.get(r['state'], r['state'])}  遥测{'开' if r['telemetry'] else '关'}  "
                  f"故障 {'、'.join(faults)}")
            print(fmt_cfg(r["cfg"]))
        elif a.cmd == "get":
            print(fmt_cfg(dev.get()["cfg"]))
        elif a.cmd == "set":
            c = apply_assignments(dev.get()["cfg"], a.items)
            r = dev.set_cfg(c)
            print(fmt_cfg(r["cfg"]))
            if c["axis_src"] != r["cfg"]["axis_src"] or c["axis_neg"] != r["cfg"]["axis_neg"]:
                print("警告：回读的轴映射与写入不一致")
            print("已生效，未保存；满意后运行 save。" + ("改了轴映射，设备会自动重新校准，请静置 1.2 秒。"
                                                      if any(i.startswith("axes=") for i in a.items) else ""))
        elif a.cmd == "save":
            dev.ok(OP_SAVE)
            print("已保存。")
        elif a.cmd == "defaults":
            r = dev.ok(OP_DEFAULTS) if a.axes else dev.set_cfg(defaults_keeping_axes(dev.get()["cfg"]))
            print(fmt_cfg(r["cfg"]))
            print("已恢复默认，轴映射也已重置，未保存；请静置 1.2 秒。" if a.axes else "已恢复默认手感，轴映射保留，未保存。")
        elif a.cmd == "cal":
            dev.ok(OP_CAL)
            print("校准中，请静置……")
            print("完成。" if dev.wait_calibrated(8.0) else "8 秒内没完成：设备在动？")
        elif a.cmd == "tel":
            dev.telemetry(a.state == "on")
            print(f"遥测已{'开' if a.state == 'on' else '关'}")
        elif a.cmd == "audio":
            print(fmt_audio(dev.ok(OP_AUDIO)["audio"]))
        elif a.cmd == "mic":
            dev.ok(OP_MIC_TEST)
            for _ in range(40):
                time.sleep(0.05)
                st = dev.ok(OP_AUDIO)["audio"]
                if not st["testing"]:
                    break
            print(fmt_audio(st))
            if st["test_valid"] and st["left_pct"] == 0:
                print("左槽全零：查 U3 焊接、BCLK/WS、MIC_DOUT")
            elif st["test_valid"] and st["right_pct"] > 50:
                print("右槽也有数据：槽位或 SELECT 不对")
        elif a.cmd == "record":
            print(f"接管 {a.seconds:.0f} 秒，按住 V 说话，松开就停。这段时间系统光标不动。")
            r = run_record(dev, a.seconds)
            print(f"按下 {len(r['v_down'])} 次，闸门打开 {len(r['ready'])} 次")
        elif a.cmd == "tone":
            print(fmt_audio(dev.ok(OP_TONE, encode_tone(a.hz, a.ms, a.atten))["audio"]))
        elif a.cmd == "dfu":
            if not Console().confirm("设备会重启进 ROM 下载模式（这段固件代码还没实测）。继续？"):
                return 1
            dev.ok(OP_DFU, b"DFU!" + bytes(12))
            print("已发送。几秒后应出现 USB-Serial-JTAG 串口，用 tools/idf.sh -p <该端口> flash 烧录；"
                  "没出现就按住 BOOT 点一下复位。")
        elif a.cmd == "tune":
            run_tune(dev)
        else:
            tel = CdcTelemetry(a.port, on_log=(lambda s: print(f"\n[固件] {s}")) if getattr(a, "log", False) else None)
            if a.cmd == "watch":
                dev.telemetry(True)
                run_watch(tel, a.seconds, a.csv)
            elif a.cmd == "wizard":
                run_wizard(dev, tel, Console())
            elif a.cmd == "still":
                run_still(dev, tel, Console(), a.seconds)
    except (E24Error, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2
    finally:
        if tel:
            try:
                dev.telemetry(False)      # 遥测 100 Hz，用完就关
            except E24Error:
                pass
            tel.close()
        if tr:
            tr.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
