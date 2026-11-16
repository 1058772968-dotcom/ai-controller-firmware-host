/* 电脑端仿真设备：用固件同一份 devcfg.c / pointer.c / protocol.c 处理配置帧与 IMU 样本，
 * 供 tools/e24ctl.py 的测试走真实 C 逻辑（避免 Python 自己对自己验证）。
 *
 * 标准输入每行一条命令，标准输出每行一条回复：
 *   status                    -> S <32 字节十六进制状态帧（报告 2，不含报告号）>
 *   session <十六进制>        -> OK            （模拟 USB 重连后 session 变化）
 *   savefail <0|1>            -> OK            （模拟 NVS 写失败）
 *   cfg <32 字节十六进制>     -> R <32 字节十六进制回复帧>（与 link_app.c 一样：成功后 set_cfg）
 *   feed gx gy gz ax ay az n  -> F <dx 累计> <dy 累计> <指向状态> <水平°/s> <竖直°/s> <静止> <零偏x y z>（传感器坐标，200 Hz）
 *   cmd <32 字节十六进制>     -> C <ak_result>   （报告 2 控制命令，走 ak_decode_command + ak_command）
 *   quit */
#include "controller.h"
#include "devcfg.h"
#include "pointer.h"
#include "protocol.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static ak_controller s_ctrl;
static ak_pointer s_ptr;
static bool s_tel, s_savefail;
static uint32_t s_now = 1000;

static void emit(void *c, const ak_event *e) { (void)c; (void)e; }
static bool do_save(void *c, const uint8_t w[AK_POINTER_WIRE_SIZE]) { (void)c; (void)w; return !s_savefail; }
static void do_cal(void *c) { (void)c; ak_pointer_calibrate(&s_ptr, s_now); }
static void do_tel(void *c, bool on) { (void)c; s_tel = on; }
static void do_dl(void *c) { (void)c; }

/* 固定的音频状态：只验证 e24ctl 与固件的帧编解码 */
static uint8_t do_audio(void *c, uint8_t op, uint32_t hz, uint32_t ms, uint32_t atten, uint8_t st[16])
{
    (void)c; (void)op; (void)hz; (void)ms; (void)atten;
    static const uint8_t fixed[16] = {0x09, 99, 0, 0, 0x28, 0xEA, 0x10, 0xF2, 0x00, 0x7D, 0, 0, 1, 0, 2, 0};
    memcpy(st, fixed, 16);
    return AK_DCFG_OK;
}

static void hex_out(const char *tag, const uint8_t *b, unsigned n)
{
    printf("%s ", tag);
    for (unsigned i = 0; i < n; i++) printf("%02x", b[i]);
    printf("\n");
}

static bool hex_in(const char *s, uint8_t *b, unsigned n)
{
    if (strlen(s) < 2 * n) return false;
    for (unsigned i = 0; i < n; i++) {
        unsigned v;
        if (sscanf(s + 2 * i, "%2x", &v) != 1) return false;
        b[i] = (uint8_t)v;
    }
    return true;
}

int main(void)
{
    ak_init(&s_ctrl, 0x12345678u, 0, s_now, emit, NULL);
    ak_pointer_init(&s_ptr, NULL);
    ak_devcfg_io io = {NULL, do_save, do_cal, do_tel, do_dl, do_audio};
    char line[512];
    setvbuf(stdout, NULL, _IOLBF, 0);
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!strncmp(line, "status", 6)) {
            uint8_t out[AK_WIRE_SIZE];
            s_ctrl.calibrated = ak_pointer_calibrated(&s_ptr);
            ak_encode_state(&s_ctrl, NULL, out);
            hex_out("S", out, AK_WIRE_SIZE);
        } else if (!strncmp(line, "session ", 8)) {
            s_ctrl.session = (uint32_t)strtoul(line + 8, NULL, 16);
            printf("OK\n");
        } else if (!strncmp(line, "savefail ", 9)) {
            s_savefail = atoi(line + 9) != 0;
            printf("OK\n");
        } else if (!strncmp(line, "cfg ", 4)) {
            uint8_t in[32], out[32];
            if (!hex_in(line + 4, in, 32)) { printf("ERR hex\n"); continue; }
            ak_pointer_cfg c = s_ptr.cfg;
            bool apply = false, after = false;
            ak_devcfg_process(&c, (uint8_t)s_ptr.state, s_tel, s_ctrl.session, in, 32, io, out, &apply, &after);
            if (apply) ak_pointer_set_cfg(&s_ptr, &c);
            hex_out("R", out, 32);
        } else if (!strncmp(line, "cmd ", 4)) {
            uint8_t in[32];
            ak_wire_command c;
            if (!hex_in(line + 4, in, 32) || !ak_decode_command(in, 32, &c)) { printf("ERR cmd frame\n"); continue; }
            printf("C %d\n", (int)ak_command(&s_ctrl, c.session, c.sequence, c.command, c.value, s_now));
        } else if (!strncmp(line, "feed ", 5)) {
            float g[3], a[3];
            int n;
            if (sscanf(line + 5, "%f %f %f %f %f %f %d", &g[0], &g[1], &g[2], &a[0], &a[1], &a[2], &n) != 7) {
                printf("ERR feed\n");
                continue;
            }
            long sx = 0, sy = 0;
            for (int i = 0; i < n; i++) {
                int16_t dx, dy;
                s_now += 5;
                ak_pointer_feed(&s_ptr, g, a, 0.005f, s_now, &dx, &dy);
                sx += dx; sy += dy;
            }
            float h, v;
            ak_pointer_last_rates(&s_ptr, &h, &v);
            printf("F %ld %ld %d %.3f %.3f %d %.3f %.3f %.3f\n", sx, sy, (int)s_ptr.state, h, v, s_ptr.still ? 1 : 0,
                   s_ptr.bias[0], s_ptr.bias[1], s_ptr.bias[2]);
        } else if (!strncmp(line, "quit", 4)) {
            break;
        } else {
            printf("ERR cmd\n");
        }
    }
    return 0;
}
