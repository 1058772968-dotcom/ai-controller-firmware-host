"""E24 四键 + 按住 V 录音联测。

上位机接管（HOST）期间固件把 hid_buttons 清零，按 L/R 不会变成电脑上的鼠标点击。
同时用 ffmpeg 从 Held-key microphone 录音，结束后对齐分析：
  - 每个键的按下/松开沿（状态报告 buttons 位，L=1 R=2 V=4 S=8）
  - V 按下 -> 请求录音 -> 闸门打开（FLAG_MIC_READY）延迟
  - V 松开 -> 闸门关闭延迟（松键截止）
  - 录音里非零段与闸门打开段是否对得上
用法：python3 keytest.py <e24ctl 所在目录> <秒数> <输出目录>
"""
import json
import os
import subprocess
import sys
import time
import wave
import array
import math

sys.path.insert(0, sys.argv[1])
import e24ctl as E  # noqa: E402

SECONDS = float(sys.argv[2])
OUT = sys.argv[3]
KEYS = {1: "L", 2: "R", 4: "V", 8: "S"}

wav_path = os.path.join(OUT, "keytest.wav")
ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "avfoundation",
                       "-i", ":Held-key microphone", "-t", str(SECONDS + 1.0), "-ac", "1", "-ar", "16000",
                       "-c:a", "pcm_s16le", wav_path])
t_ff = time.monotonic()

tr = E.HidapiTransport()
dev = E.E24(tr)
st = None
end = time.monotonic() + 2.0
while time.monotonic() < end and st is None:
    d = tr.read(50)
    if d and d[0] == E.REPORT_STATE and E.parse_state(d[1:33]):
        st = E.parse_state(d[1:33]); last_cmd_seq = int.from_bytes(d[1 + 24:1 + 28], "little")
if st is None:
    raise SystemExit("2 秒内没收到状态报告")
# 固件只收比上一条更新的序号（controller.c newer()），所以接着设备记的序号往下编
session, seq = st["session"], last_cmd_seq + 1
print(f"session 0x{session:08X}，设备记的上一条命令序号 {last_cmd_seq}，本次从 {seq} 开始", flush=True)
ACK = {0: "OK", 1: "BAD_SESSION", 2: "STALE", 3: "NOT_CONNECTED", 4: "HELD", 5: "CONFLICT", 6: "INVALID"}
EVT = {1: "EDGE", 2: "OWNER", 3: "MIC", 4: "DRAW", 5: "HAPTIC", 6: "RESET_INPUT", 7: "CENTER", 8: "ACK", 9: "FAULT"}


def send(cmd, value=0):
    global seq
    tr.write(bytes([E.REPORT_STATE]) + E.build_command(cmd, session, seq, value))
    seq += 1


events = []
t0 = time.monotonic()


def ev(kind, **kw):
    t = time.monotonic() - t0
    events.append({"t": round(t, 4), "kind": kind, **kw})
    print(f"{t:7.3f} s  {kind} {kw if kw else ''}", flush=True)


send(E.CMD_HELLO)
time.sleep(0.05)
send(E.CMD_CLAIM)
last_keep = time.monotonic()
prev_buttons, want, ready, owner, n_reports = 0, False, False, None, 0
try:
    while time.monotonic() - t0 < SECONDS:
        now = time.monotonic()
        if now - last_keep >= 0.2:
            send(E.CMD_KEEPALIVE)
            last_keep = now
        data = tr.read(20)
        r = E.parse_state(data[1:]) if data and data[0] == E.REPORT_STATE else None
        if not r or r["session"] != session:
            continue
        n_reports += 1
        typ, val, dev_ms = data[2], data[18], int.from_bytes(data[13:17], "little")
        if typ in EVT:
            ev("evt_" + EVT[typ], value=(ACK.get(val, val) if typ == 8 else val), dev_ms=dev_ms)
        if r["owner"] != owner:
            owner = r["owner"]
            ev("owner", owner=E.OWNER.get(owner, owner))
        b = r["buttons"]
        if b != prev_buttons:
            for bit, name in KEYS.items():
                if (b & bit) and not (prev_buttons & bit):
                    ev("down", key=name)
                elif not (b & bit) and (prev_buttons & bit):
                    ev("up", key=name)
            prev_buttons = b
        if r["hid_buttons"]:
            ev("hid_buttons_nonzero", value=r["hid_buttons"])
        v = bool(b & E.KEY_V)
        if v and not want:
            want = True
            send(E.CMD_RECORD, 1)
            ev("record_req")
        elif not v and want:
            want = False
        is_ready = bool(r["flags"] & E.FLAG_MIC_READY)
        if is_ready != ready:
            ready = is_ready
            ev("gate_open" if ready else "gate_closed")
finally:
    send(E.CMD_RELEASE)
    ev("release_sent")

ff.wait(timeout=15)
offset = t0 - t_ff  # ffmpeg 起点早于 t0；录音实际开始还要再晚一点（打开设备），只作粗对齐

w = wave.open(wav_path)
a = array.array("h", w.readframes(w.getnframes()))
sr = w.getframerate()
# 每 10 ms 一格：非零样本数、RMS
win = sr // 100
cells = []
for i in range(0, len(a), win):
    seg = a[i:i + win]
    nz = sum(1 for x in seg if x)
    rms = math.sqrt(sum(x * x for x in seg) / len(seg)) if seg else 0
    cells.append((i / sr, nz, rms))
# 连续非零段
segs, cur = [], None
for t, nz, rms in cells:
    if nz > 0:
        if cur is None:
            cur = [t, t + 0.01, rms]
        else:
            cur[1] = t + 0.01
            cur[2] = max(cur[2], rms)
    elif cur is not None:
        segs.append(cur)
        cur = None
if cur:
    segs.append(cur)

def dbfs(x):
    return 20 * math.log10(x / 32768) if x > 0 else -999

summary = {
    "seconds": SECONDS, "state_reports": n_reports, "report_rate_hz": round(n_reports / SECONDS, 1),
    "events": events,
    "wav": {"samples": len(a), "rate": sr, "nonzero": sum(1 for x in a if x),
            "nonzero_segments_s": [[round(s, 2), round(e, 2), round(dbfs(m), 1)] for s, e, m in segs],
            "ffmpeg_started_before_t0_s": round(offset, 3)},
}
# 闸门段（状态报告时间轴）
opens = [e["t"] for e in events if e["kind"] == "gate_open"]
closes = [e["t"] for e in events if e["kind"] == "gate_closed"]
summary["gate_segments_s"] = list(zip(opens, closes))
# V 松开 -> 闸门关闭
vups = [e["t"] for e in events if e["kind"] == "up" and e.get("key") == "V"]
vdowns = [e["t"] for e in events if e["kind"] == "down" and e.get("key") == "V"]
summary["v_down_to_gate_open_ms"] = [round((min([o for o in opens if o >= d] or [None]) - d) * 1000, 1)
                                     if [o for o in opens if o >= d] else None for d in vdowns]
summary["v_up_to_gate_closed_ms"] = [round((min([c for c in closes if c >= u]) - u) * 1000, 1)
                                     if [c for c in closes if c >= u] else None for u in vups]
json.dump(summary, open(os.path.join(OUT, "keytest.json"), "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in summary.items() if k != "events"}, ensure_ascii=False, indent=1))
