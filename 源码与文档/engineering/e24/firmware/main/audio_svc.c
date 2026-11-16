#include "audio_svc.h"
#include <math.h>
#include <stdatomic.h>
#include <string.h>
#include "audio_dsp.h"
#include "bsp_e24.h"
#include "bsp_pins.h"
#include "devcfg.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "tusb.h"

static const char *TAG = "audio";

#define MIC_TEST_FRAMES AK_AUDIO_I2S_HZ
#define MIC_TEST_SKIP_FRAMES (AK_AUDIO_I2S_HZ / 10u)   /* 手册启动 <20 ms，跳过 100 ms 再统计 */
#define AMP_ON_MS 10u                                  /* MAX98357A tON 典型 7 ms */
#define AMP_OFF_TAIL_MS 20u                            /* 渐出后再送一段零，然后才关功放 */
#define BYTES_PER_CHUNK (AK_AUDIO_CHUNK_FRAMES * 2u * sizeof(int32_t))

static i2s_chan_handle_t s_tx, s_rx;
static atomic_bool s_power, s_permit, s_abort, s_failed, s_failed_seen, s_streaming, s_clock, s_amp;
static atomic_bool s_test_req, s_test_run, s_test_valid, s_tone_run;
static atomic_uint s_rx_errors, s_uac_overflow;

static SemaphoreHandle_t s_lock;     /* 保护下面的请求和结果 */
static ak_mic_stats s_stats;
static bool s_tone_req;
static uint32_t s_tone_hz, s_tone_ms, s_tone_atten;

/* UAC 音量/静音（主机侧控件，只影响放行后的 PCM） */
static bool s_mute[2];
static int16_t s_volume[2];
static atomic_int s_gain_q15 = 32768;

static int32_t s_rx_buf[AK_AUDIO_CHUNK_FRAMES * 2];
static int32_t s_tx_buf[AK_AUDIO_CHUNK_FRAMES * 2];
static int16_t s_pcm[AK_AUDIO_PCM_SAMPLES];

static void update_gain(void)
{
    int g = (s_mute[0] || s_mute[1]) ? 0 : (int)(32768.0f * powf(10.0f, (float)(s_volume[0] + s_volume[1]) / (256.0f * 20.0f)));
    atomic_store(&s_gain_q15, g);
}

void audio_svc_set_mic(bool power, bool permit)
{
    bool was = atomic_exchange(&s_permit, permit && power);
    atomic_store(&s_power, power);
    if (was && !permit) tud_audio_clear_ep_in_ff();   /* 松键当场清掉待发音频 */
}

bool audio_svc_streaming(void)
{
    /* 总线复位不走 tud_audio_set_itf_close_ep_cb，掉配置时要自己清；
     * 挂起不算关流（恢复时主机不会重发 SET_INTERFACE），只是挂起期间不算在收 */
    if (!tud_mounted()) atomic_store(&s_streaming, false);
    return atomic_load(&s_streaming) && !tud_suspended();
}

bool audio_svc_take_abort(bool *failed)
{
    bool a = atomic_exchange(&s_abort, false);
    *failed = atomic_load(&s_failed) && !atomic_exchange(&s_failed_seen, true);
    return a || *failed;
}

static void fail_capture(void)
{
    atomic_store(&s_failed, true);
    atomic_store(&s_permit, false);
    atomic_store(&s_abort, true);
}

static esp_err_t clock_set(bool on)
{
    esp_err_t e;
    if (on) {
        e = i2s_channel_enable(s_tx);
        if (e == ESP_OK) e = i2s_channel_enable(s_rx);
    } else {
        e = i2s_channel_disable(s_rx);
        esp_err_t e2 = i2s_channel_disable(s_tx);
        if (e == ESP_OK) e = e2;
    }
    if (e == ESP_OK) atomic_store(&s_clock, on);
    return e;
}

static void amp_set(bool on)
{
    gpio_set_level(BSP_PIN_AMP_EN, on);
    atomic_store(&s_amp, on);
}

/* 主机打开了麦克风流但闸门关着：送静音，不送真实样本 */
static void uac_write(const int16_t *pcm, size_t n)
{
    if (!atomic_load(&s_streaming)) return;
    uint16_t bytes = (uint16_t)(n * sizeof(int16_t));
    if (tud_audio_write(pcm, bytes) != bytes && atomic_load(&s_permit)) {
        atomic_fetch_add(&s_uac_overflow, 1);
        atomic_store(&s_abort, true);    /* 规格 AUD 02：溢出按终止处理，不留半段录音 */
    }
}

static void audio_task(void *arg)
{
    (void)arg;
    ak_mic_filter filter;
    ak_tone tone;
    uint32_t test_skip = 0, tail_ms = 0;
    bool amp_ready = false;
    memset(&tone, 0, sizeof tone);
    ak_mic_filter_reset(&filter);

    for (;;) {
        bool mic = atomic_load(&s_power);
        bool test = atomic_load(&s_test_run);

        xSemaphoreTake(s_lock, portMAX_DELAY);
        if (atomic_exchange(&s_test_req, false)) {
            ak_mic_stats_reset(&s_stats);
            atomic_store(&s_test_valid, false);
            atomic_store(&s_test_run, true);
            test = true;
            test_skip = MIC_TEST_SKIP_FRAMES;
        }
        if (s_tone_req) {
            s_tone_req = false;
            if (!mic && ak_tone_start(&tone, s_tone_hz, s_tone_ms, s_tone_atten)) amp_ready = false;
            else atomic_store(&s_tone_run, false);     /* 录音抢先：这次不播，也不能卡在“播放中” */
        }
        xSemaphoreGive(s_lock);

        if (mic) {
            if (test) { atomic_store(&s_test_run, false); test = false; }   /* 录音优先：自检作废 */
            ak_tone_stop(&tone);
        }

        bool tone_on = ak_tone_active(&tone);
        bool want = mic || test || tone_on || tail_ms > 0;
        if (want != atomic_load(&s_clock)) {
            if (!want && atomic_load(&s_amp)) amp_set(false);
            if (clock_set(want) != ESP_OK) {
                ESP_LOGE(TAG, "I2S 时钟%s失败", want ? "启动" : "停止");
                fail_capture();
                vTaskDelay(pdMS_TO_TICKS(100));
                continue;
            }
            ak_mic_filter_reset(&filter);
        }

        if (!want) {
            /* 时钟停着也要给在收流的主机送静音，否则录音软件会报设备无数据 */
            memset(s_pcm, 0, sizeof s_pcm);
            uac_write(s_pcm, AK_AUDIO_PCM_SAMPLES);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        size_t got = 0;
        esp_err_t e = i2s_channel_read(s_rx, s_rx_buf, BYTES_PER_CHUNK, &got, 40);
        if (e != ESP_OK || got != BYTES_PER_CHUNK) {
            atomic_fetch_add(&s_rx_errors, 1);
            memset(s_rx_buf, 0, sizeof s_rx_buf);
            ak_tone_stop(&tone);
            fail_capture();
            ESP_LOGE(TAG, "I2S 读失败 %s，收到 %u 字节", esp_err_to_name(e), (unsigned)got);
        }

        /* 播放：先让功放在零数据下开好，再出声；结束后再送一段零才关 */
        if (tone_on) {
            tail_ms = AMP_OFF_TAIL_MS;
            if (!atomic_load(&s_amp)) amp_set(true);
            if (!amp_ready) {
                amp_ready = true;       /* 这一块 10 ms 的零，就是 tON 等待（auto_clear 自动送零） */
            } else {
                bool more = ak_tone_fill(&tone, s_tx_buf, AK_AUDIO_CHUNK_FRAMES);
                size_t wrote = 0;
                i2s_channel_write(s_tx, s_tx_buf, BYTES_PER_CHUNK, &wrote, 40);
                if (!more) atomic_store(&s_tone_run, false);
            }
        } else if (tail_ms > 0) {
            tail_ms = tail_ms > 10 ? tail_ms - 10 : 0;
            if (!tail_ms) { amp_set(false); atomic_store(&s_tone_run, false); }
        }

        /* 麦克风：只有闸门打开才产生 PCM；播放或自检时 RX 不外传 */
        if (atomic_load(&s_permit)) {
            size_t n = ak_mic_decimate(&filter, s_rx_buf, AK_AUDIO_CHUNK_FRAMES, AK_MIC_GAIN, s_pcm);
            int gain = atomic_load(&s_gain_q15);
            for (size_t i = 0; i < n; i++) s_pcm[i] = (int16_t)(((int32_t)s_pcm[i] * gain) / 32768);
            if (atomic_load(&s_permit)) uac_write(s_pcm, n);   /* 处理期间松键：这一块作废 */
            else { memset(s_pcm, 0, sizeof s_pcm); uac_write(s_pcm, n); }
        } else {
            ak_mic_filter_reset(&filter);
            memset(s_pcm, 0, sizeof s_pcm);
            uac_write(s_pcm, AK_AUDIO_PCM_SAMPLES);
            if (test) {
                if (test_skip >= AK_AUDIO_CHUNK_FRAMES) test_skip -= AK_AUDIO_CHUNK_FRAMES;
                else {
                    xSemaphoreTake(s_lock, portMAX_DELAY);
                    ak_mic_stats_add(&s_stats, s_rx_buf, AK_AUDIO_CHUNK_FRAMES);
                    bool done = s_stats.frames >= MIC_TEST_FRAMES;
                    xSemaphoreGive(s_lock);
                    if (done) { atomic_store(&s_test_valid, true); atomic_store(&s_test_run, false); }
                }
            }
        }
        memset(s_rx_buf, 0, sizeof s_rx_buf);
    }
}

esp_err_t audio_svc_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) return ESP_ERR_NO_MEM;

    /* 一个控制器同时建 TX/RX，共用 BCLK/WS（规格 AUD 01）。auto_clear：欠载时自动送零 */
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan.dma_desc_num = 4;
    chan.dma_frame_num = AK_AUDIO_CHUNK_FRAMES;
    chan.auto_clear = true;
    esp_err_t e = i2s_new_channel(&chan, &s_tx, &s_rx);
    if (e != ESP_OK) return e;

    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AK_AUDIO_I2S_HZ),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = BSP_PIN_I2S_BCLK,
            .ws = BSP_PIN_I2S_WS,
            .dout = BSP_PIN_SPK_DIN,
            .din = BSP_PIN_MIC_DOUT,
        },
    };
    e = i2s_channel_init_std_mode(s_tx, &std);
    if (e == ESP_OK) e = i2s_channel_init_std_mode(s_rx, &std);
    if (e != ESP_OK) return e;
    if (xTaskCreatePinnedToCore(audio_task, "audio", 4096, NULL, 8, NULL, 1) != pdPASS) return ESP_ERR_NO_MEM;
    ESP_LOGI(TAG, "I2S 全双工就绪：%u Hz，32 bit 立体声，BCLK %u Hz，时钟待命", (unsigned)AK_AUDIO_I2S_HZ, (unsigned)AK_AUDIO_I2S_HZ * 64u);
    return ESP_OK;
}

static void put16(uint8_t *p, int v) { p[0] = (uint8_t)v; p[1] = (uint8_t)((unsigned)v >> 8); }

static void encode_status(uint8_t st[16])
{
    memset(st, 0, 16);
    st[0] = (uint8_t)((atomic_load(&s_clock) ? 1 : 0) | (atomic_load(&s_permit) ? 2 : 0) |
                      (atomic_load(&s_test_run) || atomic_load(&s_test_req) ? 4 : 0) | (atomic_load(&s_test_valid) ? 8 : 0) |
                      (atomic_load(&s_tone_run) ? 16 : 0) | (atomic_load(&s_amp) ? 32 : 0) |
                      (atomic_load(&s_streaming) ? 64 : 0) | (atomic_load(&s_failed) ? 128 : 0));
    xSemaphoreTake(s_lock, portMAX_DELAY);
    ak_mic_stats s = s_stats;
    xSemaphoreGive(s_lock);
    if (s.frames) {
        st[1] = (uint8_t)(100.0 * s.left_nonzero / s.frames);
        st[2] = (uint8_t)(100.0 * s.right_nonzero / s.frames);
    }
    put16(st + 4, (int)lrintf(ak_mic_stats_rms_dbfs(&s) * 100.0f));
    put16(st + 6, (int)lrintf(ak_mic_stats_peak_dbfs(&s) * 100.0f));
    for (unsigned i = 0; i < 4; i++) st[8 + i] = (uint8_t)(s.frames >> (8 * i));
    put16(st + 12, (int)atomic_load(&s_rx_errors));
    put16(st + 14, (int)atomic_load(&s_uac_overflow));
}

uint8_t audio_svc_config(uint8_t op, uint32_t hz, uint32_t ms, uint32_t atten_db, uint8_t status[16])
{
    uint8_t code = AK_DCFG_OK;
    bool busy = atomic_load(&s_power) || atomic_load(&s_test_run) || atomic_load(&s_test_req) || atomic_load(&s_tone_run);
    if (atomic_load(&s_failed) && op != AK_DCFG_AUDIO_STATUS) code = AK_DCFG_UNAVAILABLE;
    else if (op == AK_DCFG_MIC_TEST) {
        if (busy) code = AK_DCFG_BUSY;
        else atomic_store(&s_test_req, true);
    } else if (op == AK_DCFG_SPK_TONE) {
        if (busy) code = AK_DCFG_BUSY;
        else {
            xSemaphoreTake(s_lock, portMAX_DELAY);
            s_tone_hz = hz; s_tone_ms = ms; s_tone_atten = atten_db; s_tone_req = true;
            atomic_store(&s_tone_run, true);
            xSemaphoreGive(s_lock);
            ESP_LOGI(TAG, "提示音 %u Hz %u ms -%u dB", (unsigned)hz, (unsigned)ms, (unsigned)atten_db);
        }
    }
    encode_status(status);
    return code;
}

/* ---------- UAC 回调（实体号来自 TUD_AUDIO20_MIC_ONE_CH_DESCRIPTOR：1 输入端 2 FU 3 输出端 4 时钟） ---------- */
bool tud_audio_set_itf_cb(uint8_t rhport, tusb_control_request_t const *r)
{
    (void)rhport;
    if (tu_u16_low(r->wIndex) == 4 && tu_u16_low(r->wValue) == 1) atomic_store(&s_streaming, true);
    return true;
}

bool tud_audio_set_itf_close_ep_cb(uint8_t rhport, tusb_control_request_t const *r)
{
    (void)rhport; (void)r;
    atomic_store(&s_streaming, false);
    return true;
}

bool tud_audio_get_req_entity_cb(uint8_t rhport, tusb_control_request_t const *r)
{
    unsigned entity = r->wIndex >> 8, selector = r->wValue >> 8, channel = r->wValue & 255;
    if (channel > 1) return false;
    if (entity == 4 && channel == 0) {
        if (selector == AUDIO20_CS_CTRL_SAM_FREQ) {
            if (r->bRequest == AUDIO20_CS_REQ_CUR) { uint32_t hz = AK_AUDIO_PCM_HZ; return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &hz, 4); }
            if (r->bRequest == AUDIO20_CS_REQ_RANGE) {
                audio20_control_range_4_n_t(1) range = {.wNumSubRanges = 1, .subrange = {{AK_AUDIO_PCM_HZ, AK_AUDIO_PCM_HZ, 0}}};
                return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &range, sizeof range);
            }
        }
        if (selector == AUDIO20_CS_CTRL_CLK_VALID && r->bRequest == AUDIO20_CS_REQ_CUR) { uint8_t valid = 1; return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &valid, 1); }
    }
    if (entity == 1 && channel == 0 && selector == AUDIO20_TE_CTRL_CONNECTOR && r->bRequest == AUDIO20_CS_REQ_CUR) {
        audio20_desc_channel_cluster_t cluster = {.bNrChannels = 1, .bmChannelConfig = 0, .iChannelNames = 0};
        return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &cluster, sizeof cluster);
    }
    if (entity == 2) {
        if (selector == AUDIO20_FU_CTRL_MUTE && r->bRequest == AUDIO20_CS_REQ_CUR) { uint8_t v = s_mute[channel]; return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &v, 1); }
        if (selector == AUDIO20_FU_CTRL_VOLUME) {
            if (r->bRequest == AUDIO20_CS_REQ_CUR) return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &s_volume[channel], 2);
            if (r->bRequest == AUDIO20_CS_REQ_RANGE) {
                audio20_control_range_2_n_t(1) range = {.wNumSubRanges = 1, .subrange = {{-60 * 256, 0, 256}}};
                return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &range, sizeof range);
            }
        }
    }
    return false;
}

bool tud_audio_set_req_entity_cb(uint8_t rhport, tusb_control_request_t const *r, uint8_t *data)
{
    (void)rhport;
    unsigned entity = r->wIndex >> 8, selector = r->wValue >> 8, channel = r->wValue & 255;
    if (entity != 2 || channel > 1 || r->bRequest != AUDIO20_CS_REQ_CUR) return false;
    if (selector == AUDIO20_FU_CTRL_MUTE && r->wLength == 1 && data[0] <= 1) s_mute[channel] = data[0];
    else if (selector == AUDIO20_FU_CTRL_VOLUME && r->wLength == 2) {
        int16_t v = (int16_t)((uint16_t)data[0] | (uint16_t)data[1] << 8);
        if (v > 0 || v < -60 * 256 || v % 256) return false;
        s_volume[channel] = v;
    } else return false;
    update_gain();
    return true;
}
