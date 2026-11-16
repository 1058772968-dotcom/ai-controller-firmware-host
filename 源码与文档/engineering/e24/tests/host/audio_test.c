/* 音频纯逻辑：FIR 频响、24 bit 取位、电平统计、提示音包络。 */
#include "audio_dsp.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PI 3.14159265358979323846
#define N 32000

static int32_t lr[2 * N];
static int16_t pcm[N / 2];

/* 用 24 bit 样本放进 32 bit 槽的高位，右槽填干扰，确认只取左槽 */
static double through(double hz, double amp)
{
    for (int i = 0; i < N; i++) {
        lr[2 * i] = (int32_t)(amp * 8388607.0 * sin(2 * PI * hz * i / 32000.0)) * 256;
        lr[2 * i + 1] = 0x7fffff00;
    }
    ak_mic_filter f; ak_mic_filter_reset(&f);
    size_t n = 0;
    for (int i = 0; i < N; i += AK_AUDIO_CHUNK_FRAMES)
        n += ak_mic_decimate(&f, lr + 2 * i, AK_AUDIO_CHUNK_FRAMES, 1.0f, pcm + n);
    assert(n == N / 2);
    double s = 0;
    for (size_t i = 200; i < n; i++) s += (double)pcm[i] * pcm[i];
    return 20 * log10(sqrt(s / (double)(n - 200)) / (amp * 32768.0 / sqrt(2.0)) + 1e-12);
}

static void filter_response(void)
{
    double sum = 0;
    for (int i = 0; i < AK_FIR_TAPS; i++) sum += ak_fir_coeffs[i];
    assert(fabs(sum - 1.0) < 1e-5);
    for (int i = 0; i < AK_FIR_TAPS / 2; i++) assert(ak_fir_coeffs[i] == ak_fir_coeffs[AK_FIR_TAPS - 1 - i]);
    assert(fabs(through(1000, 0.5)) < 0.1);
    assert(fabs(through(4000, 0.5)) < 0.2);
    assert(through(9000, 0.5) < -60);    /* 折到 7 kHz */
    assert(through(12000, 0.5) < -60);   /* 折到 4 kHz，语音频带内 */
    assert(through(15000, 0.5) < -60);
}

static void gain_and_clip(void)
{
    for (int i = 0; i < 2000; i++) { lr[2 * i] = (int32_t)0x7fffff00; lr[2 * i + 1] = 0; }
    ak_mic_filter f; ak_mic_filter_reset(&f);
    size_t n = ak_mic_decimate(&f, lr, 2000, 4.0f, pcm);
    assert(n == 1000 && pcm[n - 1] == 32767);
    for (int i = 0; i < 2000; i++) lr[2 * i] = (int32_t)0x80000000;
    ak_mic_filter_reset(&f);
    n = ak_mic_decimate(&f, lr, 2000, 4.0f, pcm);
    assert(pcm[n - 1] == -32768);
    /* 负数 24 bit 必须算术移位：-1 LSB 不能变成大正数 */
    for (int i = 0; i < 2000; i++) lr[2 * i] = -256 * 256;
    ak_mic_filter_reset(&f);
    n = ak_mic_decimate(&f, lr, 2000, 1.0f, pcm);
    assert(pcm[n - 1] == -1);
}

static void stats(void)
{
    ak_mic_stats s; ak_mic_stats_reset(&s);
    assert(ak_mic_stats_rms_dbfs(&s) == -120.0f && ak_mic_stats_peak_dbfs(&s) == -120.0f);
    for (int i = 0; i < N; i++) {   /* -26 dBFS 正弦 + 直流，右槽全零 */
        double a = pow(10, -26.0 / 20) * sqrt(2.0);
        lr[2 * i] = ((int32_t)(a * 8388607.0 * sin(2 * PI * 1000 * i / 32000.0)) + 5000) * 256;
        lr[2 * i + 1] = 0;
    }
    ak_mic_stats_add(&s, lr, N);
    assert(s.frames == N && s.right_nonzero == 0 && s.left_nonzero > N * 9 / 10);
    assert(fabsf(ak_mic_stats_rms_dbfs(&s) + 26.0f) < 0.05f);   /* 直流不算进 RMS */
    assert(ak_mic_stats_peak_dbfs(&s) > -24.0f);
    memset(lr, 0, sizeof lr);
    ak_mic_stats_reset(&s);
    ak_mic_stats_add(&s, lr, N);
    assert(s.left_nonzero == 0 && ak_mic_stats_rms_dbfs(&s) == -120.0f);
}

/* 相邻样本跳变不能超过稳态正弦的最大步进太多：包络必须连续 */
static double max_step(const int32_t *x, size_t frames)
{
    double m = 0;
    for (size_t i = 1; i < frames; i++) { double d = fabs((double)x[2 * i] - x[2 * i - 2]); if (d > m) m = d; }
    return m;
}

static void tone(void)
{
    ak_tone t;
    assert(!ak_tone_start(&t, 100, 100, 40) && !ak_tone_active(&t));
    assert(!ak_tone_start(&t, 1000, 2000, 40) && !ak_tone_start(&t, 1000, 100, 20) && !ak_tone_start(&t, 9000, 100, 40));
    assert(ak_tone_start(&t, 1000, 100, 40));
    size_t total = 3200, frames = total + 320;
    assert(!ak_tone_fill(&t, lr, frames) && !ak_tone_active(&t));
    double peak = 0;
    for (size_t i = 0; i < frames; i++) { assert(lr[2 * i + 1] == 0); if (fabs((double)lr[2 * i]) > peak) peak = fabs((double)lr[2 * i]); }
    assert(fabs(20 * log10(peak / 2147483648.0) + 40) < 0.1);
    assert(lr[0] == 0 && llabs((long long)lr[2 * (total - 1)]) < peak / 50);    /* 开头结尾都归零 */
    for (size_t i = total; i < frames; i++) assert(lr[2 * i] == 0);            /* 结束后是真零 */
    double sine_step = peak * 2 * PI * 1000 / 32000;
    assert(max_step(lr, frames) < sine_step * 1.1);

    /* 抢占：中途停止走 5 ms 渐出，不是硬切 */
    assert(ak_tone_start(&t, 1000, 1000, 40));
    ak_tone_fill(&t, lr, 3200);
    ak_tone_stop(&t);
    assert(ak_tone_active(&t));
    assert(!ak_tone_fill(&t, lr, AK_TONE_FADE_FRAMES + 10));
    assert(max_step(lr, AK_TONE_FADE_FRAMES + 10) < sine_step * 1.1);

    /* 刚开始就被抢占：还在渐入段，也不能跳 */
    assert(ak_tone_start(&t, 1000, 1000, 40));
    ak_tone_fill(&t, lr, 40);
    ak_tone_stop(&t);
    assert(!ak_tone_fill(&t, lr, AK_TONE_FADE_FRAMES + 10));
    assert(max_step(lr, AK_TONE_FADE_FRAMES + 10) < sine_step * 1.1);

    /* 最短音：渐入渐出各占一半 */
    assert(ak_tone_start(&t, 200, 10, 30));
    assert(!ak_tone_fill(&t, lr, 320));
}

int main(void)
{
    filter_response();
    gain_and_clip();
    stats();
    tone();
    puts("PASS 音频：FIR 频响与抗混叠、只取左槽、增益限幅、算术移位、电平统计、提示音包络与抢占");
    return 0;
}
