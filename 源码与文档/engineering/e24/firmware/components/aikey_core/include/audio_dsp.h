#ifndef AIKEY_AUDIO_DSP_H
#define AIKEY_AUDIO_DSP_H
/* 音频纯逻辑：不依赖 IDF，可在电脑端单元测试。
 *
 * I2S 帧：立体声，每槽 32 bit，lr[2n] 左槽、lr[2n+1] 右槽。
 * ICS-43434（手册 DS-000069）：24 bit 补码，MSB 在前，SELECT 接地输出左槽，
 *   所以 32 bit 槽里高 24 位是数据。灵敏度 -26 dBFS @ 94 dB SPL。
 * MAX98357A：SD_MODE 约 3.2 V 时取左槽，右槽写零。 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "audio_fir.h"

#define AK_AUDIO_I2S_HZ 32000u
#define AK_AUDIO_PCM_HZ 16000u
#define AK_AUDIO_CHUNK_FRAMES 320u    /* 10 ms */
#define AK_AUDIO_PCM_SAMPLES 160u     /* 10 ms，16 kHz */
#define AK_MIC_GAIN 4.0f              /* +12 dB 起点：手册灵敏度下语音电平偏低，待用已知声源标定 */

/* 提示音边界。扬声器参数未冻结（规格 AUD 03），音量上限压得很低。 */
#define AK_TONE_MIN_HZ 200u
#define AK_TONE_MAX_HZ 4000u
#define AK_TONE_MAX_MS 1000u
#define AK_TONE_MIN_ATTEN_DB 30u      /* 至少比满幅低 30 dB */
#define AK_TONE_MAX_ATTEN_DB 80u
#define AK_TONE_FADE_FRAMES 160u      /* 5 ms 渐入渐出，防爆音 */

typedef struct { float hist[AK_FIR_TAPS]; unsigned pos, phase; } ak_mic_filter;

void ak_mic_filter_reset(ak_mic_filter *f);
/* 取左槽 → 抗混叠 → 2:1 抽取 → 增益 → 限幅到 int16。返回写入 out 的样本数（frames 的一半）。 */
size_t ak_mic_decimate(ak_mic_filter *f, const int32_t *lr, size_t frames, float gain, int16_t *out);

/* 麦克风自检：只统计电平，不保留波形 */
typedef struct {
    uint32_t frames, left_nonzero, right_nonzero;
    int32_t peak;          /* 左槽 24 bit 绝对值峰值 */
    double sum, sum2;      /* 左槽 24 bit 求和与平方和 */
} ak_mic_stats;
void ak_mic_stats_reset(ak_mic_stats *s);
void ak_mic_stats_add(ak_mic_stats *s, const int32_t *lr, size_t frames);
/* 去掉直流后的 RMS，以及峰值，单位 dBFS（满幅 = 2^23）。没有信号时返回 -120 */
float ak_mic_stats_rms_dbfs(const ak_mic_stats *s);
float ak_mic_stats_peak_dbfs(const ak_mic_stats *s);

typedef struct {
    float phase, step, amp;
    uint32_t pos, total, fade;
} ak_tone;

static inline bool ak_tone_params_ok(uint32_t hz, uint32_t ms, uint32_t atten_db)
{
    return hz >= AK_TONE_MIN_HZ && hz <= AK_TONE_MAX_HZ && ms >= 10u && ms <= AK_TONE_MAX_MS &&
           atten_db >= AK_TONE_MIN_ATTEN_DB && atten_db <= AK_TONE_MAX_ATTEN_DB;
}
bool ak_tone_start(ak_tone *t, uint32_t hz, uint32_t ms, uint32_t atten_db);
/* 马上转入渐出（录音抢占时用） */
void ak_tone_stop(ak_tone *t);
bool ak_tone_active(const ak_tone *t);
/* 写 frames 帧：左槽出音，右槽零；结束后写零。返回写完后是否还在播放 */
bool ak_tone_fill(ak_tone *t, int32_t *lr, size_t frames);
#endif
