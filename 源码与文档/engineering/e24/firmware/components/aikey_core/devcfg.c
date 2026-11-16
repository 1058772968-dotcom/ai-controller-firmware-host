#include "devcfg.h"
#include "audio_dsp.h"
#include "protocol.h"
#include <string.h>

static uint32_t get32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static void put32(uint8_t *p, uint32_t v) { for (unsigned i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i)); }
static bool zero(const uint8_t *p, unsigned n) { for (unsigned i = 0; i < n; i++) if (p[i]) return false; return true; }

void ak_devcfg_process(ak_pointer_cfg *cfg, uint8_t state, bool telemetry_on, uint32_t session,
                       const uint8_t *in, unsigned len, ak_devcfg_io io,
                       uint8_t out[32], bool *apply, bool *download_after)
{
    *apply = false;
    *download_after = false;
    uint8_t code = AK_DCFG_OK;
    uint8_t audio[16];
    bool audio_reply = false;
    uint8_t op = in && len > 1 ? in[1] : 0;
    uint32_t tx = in && len == 32 ? get32(in + 8) : 0;
    const uint8_t *pl = in ? in + 12 : NULL;

    bool frame = in && len == 32 && in[0] == 1 && ak_devcfg_owns(in, len) && !in[2] && !in[3] && !in[28] && !in[29];
    if (frame) {
        uint16_t crc = ak_crc16(in, 30);
        frame = in[30] == (uint8_t)crc && in[31] == (uint8_t)(crc >> 8);
    }
    if (!frame) code = AK_DCFG_FRAME;
    else if (get32(in + 4) != session) code = AK_DCFG_SESSION;
    else switch (op) {
    case AK_DCFG_PTR_GET:
    case AK_DCFG_PTR_DEFAULTS:
    case AK_DCFG_GYRO_CAL:
    case AK_DCFG_PTR_SAVE:
        if (!zero(pl, 16)) { code = AK_DCFG_VALUE; break; }
        if (op == AK_DCFG_PTR_DEFAULTS) { ak_pointer_default_cfg(cfg); *apply = true; }
        if (op == AK_DCFG_GYRO_CAL && io.calibrate) io.calibrate(io.ctx);
        if (op == AK_DCFG_PTR_SAVE) {
            uint8_t w[AK_POINTER_WIRE_SIZE];
            ak_pointer_cfg_encode(cfg, w);
            if (!io.save || !io.save(io.ctx, w)) code = AK_DCFG_STORAGE;
        }
        break;
    case AK_DCFG_PTR_SET: {
        ak_pointer_cfg next;
        if (!ak_pointer_cfg_decode(pl, &next)) { code = AK_DCFG_VALUE; break; }
        *cfg = next;
        *apply = true;
        break;
    }
    case AK_DCFG_TELEMETRY:
        if (pl[0] > 1 || !zero(pl + 1, 15)) { code = AK_DCFG_VALUE; break; }
        telemetry_on = pl[0] == 1;
        if (io.telemetry) io.telemetry(io.ctx, telemetry_on);
        break;
    case AK_DCFG_DOWNLOAD:
        if (memcmp(pl, "DFU!", 4) || !zero(pl + 4, 12)) { code = AK_DCFG_VALUE; break; }
        *download_after = io.download != NULL;
        break;
    case AK_DCFG_AUDIO_STATUS:
    case AK_DCFG_MIC_TEST:
    case AK_DCFG_SPK_TONE: {
        uint32_t hz = 0, ms = 0, atten = 0;
        if (op == AK_DCFG_SPK_TONE) {
            hz = (uint32_t)pl[4] | (uint32_t)pl[5] << 8;
            ms = (uint32_t)pl[6] | (uint32_t)pl[7] << 8;
            atten = pl[8];
            if (memcmp(pl, "SPK!", 4) || !zero(pl + 9, 7) || !ak_tone_params_ok(hz, ms, atten)) { code = AK_DCFG_VALUE; break; }
        } else if (!zero(pl, 16)) { code = AK_DCFG_VALUE; break; }
        if (!io.audio) { code = AK_DCFG_UNAVAILABLE; break; }
        code = io.audio(io.ctx, op, hz, ms, atten, audio);
        audio_reply = true;
        break;
    }
    default:
        code = AK_DCFG_FRAME;
        break;
    }

    memset(out, 0, 32);
    out[0] = 1;
    out[1] = (uint8_t)(op | 0x80);
    out[2] = code;
    out[3] = state;
    put32(out + 4, session);
    put32(out + 8, tx);
    if (audio_reply) memcpy(out + 12, audio, 16);
    else ak_pointer_cfg_encode(cfg, out + 12);
    out[28] = telemetry_on ? 1 : 0;
    uint16_t crc = ak_crc16(out, 30);
    out[30] = (uint8_t)crc;
    out[31] = (uint8_t)(crc >> 8);
}
