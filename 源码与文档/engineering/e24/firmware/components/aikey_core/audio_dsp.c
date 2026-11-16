#include "audio_dsp.h"
#include <math.h>
#include <string.h>

#define FULL_SCALE_24 8388608.0
#define TWO_PI 6.2831853071795864f

void ak_mic_filter_reset(ak_mic_filter *f) { memset(f, 0, sizeof *f); }

size_t ak_mic_decimate(ak_mic_filter *f, const int32_t *lr, size_t frames, float gain, int16_t *out)
{
    size_t n = 0;
    for (size_t i = 0; i < frames; i++) {
        f->hist[f->pos] = (float)(lr[2 * i] >> 8) * (1.0f / 256.0f);   /* 24 bit -> int16 量级 */
        f->pos = (f->pos + 1) % AK_FIR_TAPS;
        if (++f->phase < 2) continue;
        f->phase = 0;
        float acc = 0;
        unsigned p = f->pos;
        for (unsigned j = 0; j < AK_FIR_TAPS; j++) {
            p = (p + AK_FIR_TAPS - 1) % AK_FIR_TAPS;
            acc += ak_fir_coeffs[j] * f->hist[p];
        }
        acc *= gain;
        if (acc > 32767.0f) acc = 32767.0f;
        if (acc < -32768.0f) acc = -32768.0f;
        out[n++] = (int16_t)lrintf(acc);
    }
    return n;
}

void ak_mic_stats_reset(ak_mic_stats *s) { memset(s, 0, sizeof *s); }

void ak_mic_stats_add(ak_mic_stats *s, const int32_t *lr, size_t frames)
{
    for (size_t i = 0; i < frames; i++) {
        int32_t l = lr[2 * i] >> 8, r = lr[2 * i + 1] >> 8;
        int32_t a = l < 0 ? -l : l;
        if (a > s->peak) s->peak = a;
        if (l) s->left_nonzero++;
        if (r) s->right_nonzero++;
        s->sum += l;
        s->sum2 += (double)l * l;
    }
    s->frames += (uint32_t)frames;
}

float ak_mic_stats_rms_dbfs(const ak_mic_stats *s)
{
    if (!s->frames) return -120.0f;
    double mean = s->sum / s->frames, var = s->sum2 / s->frames - mean * mean;
    if (var < 1.0) return -120.0f;
    return (float)(20.0 * log10(sqrt(var) / FULL_SCALE_24));
}

float ak_mic_stats_peak_dbfs(const ak_mic_stats *s)
{
    return s->peak ? (float)(20.0 * log10(s->peak / FULL_SCALE_24)) : -120.0f;
}

bool ak_tone_start(ak_tone *t, uint32_t hz, uint32_t ms, uint32_t atten_db)
{
    memset(t, 0, sizeof *t);
    if (!ak_tone_params_ok(hz, ms, atten_db)) return false;
    t->step = TWO_PI * (float)hz / (float)AK_AUDIO_I2S_HZ;
    t->amp = 2147483392.0f * powf(10.0f, -(float)atten_db / 20.0f);
    t->total = ms * (AK_AUDIO_I2S_HZ / 1000u);
    t->fade = t->total / 2 < AK_TONE_FADE_FRAMES ? t->total / 2 : AK_TONE_FADE_FRAMES;
    return true;
}

bool ak_tone_active(const ak_tone *t) { return t->pos < t->total; }

void ak_tone_stop(ak_tone *t)
{
    if (!ak_tone_active(t)) return;
    uint32_t left = t->total - t->pos;
    if (left > t->fade) t->total = t->pos + t->fade;   /* 还没到渐出段：从现在起渐出 */
    /* 渐入中被打断时，包络取 min(渐入, 渐出)，不会跳变 */
}

bool ak_tone_fill(ak_tone *t, int32_t *lr, size_t frames)
{
    for (size_t i = 0; i < frames; i++) {
        int32_t v = 0;
        if (ak_tone_active(t)) {
            uint32_t in = t->pos, out = t->total - 1 - t->pos;
            uint32_t edge = in < out ? in : out;
            float env = edge < t->fade && t->fade ? (float)edge / (float)t->fade : 1.0f;
            v = (int32_t)(t->amp * env * sinf(t->phase));
            t->phase += t->step;
            if (t->phase >= TWO_PI) t->phase -= TWO_PI;
            t->pos++;
        }
        lr[2 * i] = v;
        lr[2 * i + 1] = 0;
    }
    return ak_tone_active(t);
}
