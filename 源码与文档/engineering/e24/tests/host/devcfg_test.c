#include "devcfg.h"
#include "protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static int saved, cals, tele = -1, dl;
static uint8_t last_saved[AK_POINTER_WIRE_SIZE];
static bool do_save(void *c, const uint8_t w[AK_POINTER_WIRE_SIZE]) { (void)c; saved++; memcpy(last_saved, w, sizeof last_saved); return true; }
static unsigned audio_calls, audio_op, audio_hz, audio_ms, audio_atten;
static uint8_t audio_code = AK_DCFG_OK;
static uint8_t audio_cb(void *c, uint8_t op, uint32_t hz, uint32_t ms, uint32_t atten, uint8_t st[16])
{
    (void)c; audio_calls++; audio_op = op; audio_hz = hz; audio_ms = ms; audio_atten = atten;
    memset(st, 0, 16); st[0] = 0xA5; st[15] = 0x5A;
    return audio_code;
}

static void do_cal(void *c) { (void)c; cals++; }
static void do_tele(void *c, bool on) { (void)c; tele = on; }
static void do_dl(void *c) { (void)c; dl++; }

static void frame(uint8_t b[32], uint8_t op, uint32_t session, const uint8_t *payload)
{
    memset(b, 0, 32);
    b[0] = 1; b[1] = op;
    for (int i = 0; i < 4; i++) { b[4 + i] = (uint8_t)(session >> (8 * i)); b[8 + i] = (uint8_t)(0x55 + i); }
    if (payload) memcpy(b + 12, payload, 16);
    uint16_t c = ak_crc16(b, 30); b[30] = (uint8_t)c; b[31] = (uint8_t)(c >> 8);
}

static void check_reply(const uint8_t r[32], uint8_t op, uint8_t code)
{
    uint16_t c = ak_crc16(r, 30);
    assert(r[30] == (uint8_t)c && r[31] == (uint8_t)(c >> 8));
    assert(r[0] == 1 && r[1] == (op | 0x80) && r[2] == code);
    assert(r[8] == 0x55 && r[11] == 0x58);
}

int main(void)
{
    ak_devcfg_io io = {NULL, do_save, do_cal, do_tele, do_dl, NULL};
    ak_pointer_cfg cfg; ak_pointer_default_cfg(&cfg);
    uint8_t in[32], out[32]; bool apply, after;
    const uint32_t S = 0x12345678;

    frame(in, AK_DCFG_PTR_GET, S, NULL);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    check_reply(out, AK_DCFG_PTR_GET, AK_DCFG_OK);
    assert(!apply && out[3] == 2);
    ak_pointer_cfg got; assert(ak_pointer_cfg_decode(out + 12, &got) && got.click_freeze_ms == cfg.click_freeze_ms);

    ak_pointer_cfg next = cfg; next.counts_per_deg = 40; next.invert_y = true;
    uint8_t w[16]; ak_pointer_cfg_encode(&next, w);
    frame(in, AK_DCFG_PTR_SET, S, w);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    check_reply(out, AK_DCFG_PTR_SET, AK_DCFG_OK);
    assert(apply && cfg.counts_per_deg == 40 && cfg.invert_y);

    frame(in, AK_DCFG_PTR_SAVE, S, NULL);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    check_reply(out, AK_DCFG_PTR_SAVE, AK_DCFG_OK);
    assert(saved == 1 && last_saved[0] == (uint8_t)4000 && last_saved[1] == (uint8_t)(4000 >> 8));

    frame(in, AK_DCFG_GYRO_CAL, S, NULL);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(cals == 1);

    uint8_t on[16] = {1};
    frame(in, AK_DCFG_TELEMETRY, S, on);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    check_reply(out, AK_DCFG_TELEMETRY, AK_DCFG_OK);
    assert(tele == 1 && out[28] == 1);

    uint8_t dfu[16] = {'D', 'F', 'U', '!'};
    frame(in, AK_DCFG_DOWNLOAD, S, dfu);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(after && dl == 0);  /* 由调用方在回复发出后执行 */

    /* 反例：错 session、坏 CRC、非法参数、下载口令不对、保留字节非零 */
    frame(in, AK_DCFG_PTR_GET, S + 1, NULL);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(out[2] == AK_DCFG_SESSION);
    frame(in, AK_DCFG_PTR_GET, S, NULL); in[30] ^= 1;
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(out[2] == AK_DCFG_FRAME);
    uint8_t bad[16]; memcpy(bad, w, 16); bad[15] = 1;
    frame(in, AK_DCFG_PTR_SET, S, bad);
    float before = cfg.counts_per_deg;
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(out[2] == AK_DCFG_VALUE && !apply && cfg.counts_per_deg == before);
    uint8_t nope[16] = {'D', 'F', 'U', '?'};
    frame(in, AK_DCFG_DOWNLOAD, S, nope);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(out[2] == AK_DCFG_VALUE && !after);
    frame(in, AK_DCFG_PTR_GET, S, NULL); in[28] = 1; { uint16_t c = ak_crc16(in, 30); in[30] = (uint8_t)c; in[31] = (uint8_t)(c >> 8); }
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(out[2] == AK_DCFG_FRAME);
    assert(!ak_devcfg_owns(in, 31));
    frame(in, 3, S, NULL); assert(!ak_devcfg_owns(in, 32));  /* REV A 的 op 留给原配置事务 */

    frame(in, AK_DCFG_PTR_DEFAULTS, S, NULL);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    assert(apply && cfg.counts_per_deg == 28.0f && !cfg.invert_y);

    /* 音频操作：无回调时明确回 UNAVAILABLE；口令、频率、时长、音量越界都不送到回调 */
    frame(in, AK_DCFG_AUDIO_STATUS, S, NULL);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, io, out, &apply, &after);
    check_reply(out, AK_DCFG_AUDIO_STATUS, AK_DCFG_UNAVAILABLE);
    ak_devcfg_io aio = io; aio.audio = audio_cb;
    frame(in, AK_DCFG_AUDIO_STATUS, S, NULL);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, aio, out, &apply, &after);
    check_reply(out, AK_DCFG_AUDIO_STATUS, AK_DCFG_OK);
    assert(audio_calls == 1 && audio_op == AK_DCFG_AUDIO_STATUS && out[12] == 0xA5 && out[27] == 0x5A);
    uint8_t dirty[16] = {1};
    frame(in, AK_DCFG_MIC_TEST, S, dirty);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, aio, out, &apply, &after);
    assert(out[2] == AK_DCFG_VALUE && audio_calls == 1);
    frame(in, AK_DCFG_MIC_TEST, S, NULL);
    audio_code = AK_DCFG_BUSY;
    ak_devcfg_process(&cfg, 2, false, S, in, 32, aio, out, &apply, &after);
    assert(out[2] == AK_DCFG_BUSY && audio_calls == 2);
    audio_code = AK_DCFG_OK;
    uint8_t tone[16] = {'S', 'P', 'K', '!', 0xE8, 0x03, 0xC8, 0x00, 40};   /* 1000 Hz，200 ms，-40 dB */
    frame(in, AK_DCFG_SPK_TONE, S, tone);
    ak_devcfg_process(&cfg, 2, false, S, in, 32, aio, out, &apply, &after);
    assert(out[2] == AK_DCFG_OK && audio_hz == 1000 && audio_ms == 200 && audio_atten == 40 && audio_calls == 3);
    static const struct { unsigned at; uint8_t v; } bad_tone[] = {{0, 'X'}, {4, 0x10}, {5, 0x20}, {7, 0x10}, {8, 29}, {8, 81}, {9, 1}};
    for (unsigned i = 0; i < sizeof bad_tone / sizeof bad_tone[0]; i++) {
        uint8_t t[16]; memcpy(t, tone, 16); t[bad_tone[i].at] = bad_tone[i].v;
        if (bad_tone[i].at == 4) t[5] = 0;                  /* 16 Hz */
        frame(in, AK_DCFG_SPK_TONE, S, t);
        ak_devcfg_process(&cfg, 2, false, S, in, 32, aio, out, &apply, &after);
        assert(out[2] == AK_DCFG_VALUE && audio_calls == 3);
    }
    frame(in, 0x1A, S, NULL); assert(!ak_devcfg_owns(in, 32));

    puts("PASS 配置通道：读/写/保存/校准/遥测/下载口令/默认值；错 session/CRC/参数/口令/保留字节均拒绝");
    return 0;
}
