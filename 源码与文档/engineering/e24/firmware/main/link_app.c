/* E24 联调档主程序。
 *
 * 任务划分：
 *   imu 任务（核 1）：等 BMI270 数据就绪中断 → 读样本 → 指向核心 → 累加位移；可选 JSON 遥测
 *   主循环（1 ms）：按键 → 控制核心；USB 命令/配置；按优先级每次只发一个 HID 报告：
 *                  配置回复 > 控制事件 > 鼠标按键变化 > 周期状态 > 位移
 * POINTER 归属：位移走标准鼠标（报告 1，int8，超出部分留到下一帧，不丢）
 * HOST 归属：位移走 0x81 运动报告（报告 2，int16），电脑端自己移光标，不再平滑
 *
 * 音频见 audio_svc.c：主循环只把隐私闸门结果交给它。
 * 本档未实现：触觉、充电器配置。对应命令按故障位明确拒绝，不假装成功。 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "app.h"
#include "audio_svc.h"
#include "bsp_e24.h"
#include "bsp_i2c.h"
#include "sdkconfig.h"
#include "controller.h"
#include "devcfg.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "imu_bmi270.h"
#include "nvs_flash.h"
#include "pointer.h"
#include "protocol.h"
#include "ptr_store.h"
#include "usb_link.h"

static const char *TAG = "e24";

/* hardware_faults 位（与 REV A / 电脑端一致）：1 IMU，2 音频，4 触觉 */
#define FAULT_IMU 1u
#define FAULT_AUDIO 2u
#define FAULT_HAPTIC 4u

static ak_controller s_ctrl;
static ak_pointer s_ptr;
static SemaphoreHandle_t s_lock;          /* 保护 s_ptr 与位移累加 */
static int32_t s_acc_x, s_acc_y;          /* 未发出的位移 */
static volatile bool s_telemetry;
static volatile bool s_imu_ok, s_imu_go;
static QueueHandle_t s_events;            /* 已编码的 32 字节事件包 */
static TaskHandle_t s_imu_task;

static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }

static void on_event(void *ctx, const ak_event *e)
{
    (void)ctx;
    if (!usb_link_mounted()) return;
    uint8_t pkt[AK_WIRE_SIZE];
    ak_encode_state(&s_ctrl, e, pkt);
    if (xQueueSend(s_events, pkt, 0) != pdTRUE) ESP_LOGW(TAG, "事件队列满，丢弃 type=%u", e->type);
}

/* ---------- 配置通道回调 ---------- */
static bool cfg_save(void *ctx, const uint8_t w[AK_POINTER_WIRE_SIZE]) { (void)ctx; return ptr_store_save(w); }
static void cfg_calibrate(void *ctx)
{
    (void)ctx;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    ak_pointer_calibrate(&s_ptr, now_ms());
    s_acc_x = s_acc_y = 0;
    xSemaphoreGive(s_lock);
    ESP_LOGI(TAG, "开始陀螺仪校准：请静置约 1.2 s");
}
static void cfg_telemetry(void *ctx, bool on) { (void)ctx; s_telemetry = on; ESP_LOGI(TAG, "遥测 %s", on ? "开" : "关"); }
static uint8_t cfg_audio(void *ctx, uint8_t op, uint32_t hz, uint32_t ms, uint32_t atten, uint8_t status[16])
{
    (void)ctx;
    return audio_svc_config(op, hz, ms, atten, status);
}
static void cfg_download(void *ctx) { (void)ctx; ESP_LOGW(TAG, "重启进下载模式"); vTaskDelay(pdMS_TO_TICKS(50)); usb_link_reboot_to_download(); }

/* ---------- IMU 任务 ---------- */
static void imu_task(void *arg)
{
    (void)arg;
    uint32_t last_tel = 0, errors = 0;
    while (!s_imu_go) ulTaskNotifyTake(pdTRUE, portMAX_DELAY);   /* imu_init 成功后才开始读 */
    for (;;) {
        /* 数据就绪中断；超时则按轮询读一次（中断线异常时仍能工作，但会在日志里体现） */
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(20));
        imu_sample_t s;
        if (imu_read(&s) != ESP_OK) {
            if (++errors == 10) {
                s_imu_ok = false;
                ESP_LOGE(TAG, "IMU 连续读失败，停用指向（重启后恢复）");
                for (;;) ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
            }
            continue;
        }
        errors = 0;
        if (s.dt <= 0) continue;
        uint32_t t = now_ms();
        int16_t dx = 0, dy = 0;
        float h = 0, v = 0;
        xSemaphoreTake(s_lock, portMAX_DELAY);
        bool moved = ak_pointer_feed(&s_ptr, s.gyro_dps, s.accel_g, s.dt, t, &dx, &dy);
        if (moved) { s_acc_x += dx; s_acc_y += dy; }
        ak_pointer_last_rates(&s_ptr, &h, &v);
        ak_pointer_state st = s_ptr.state;
        bool still = s_ptr.still;
        float bias[3] = {s_ptr.bias[0], s_ptr.bias[1], s_ptr.bias[2]};
        xSemaphoreGive(s_lock);

        if (s_telemetry && t - last_tel >= 10) {   /* 100 Hz JSON 行，供电脑端调参与画图 */
            last_tel = t;
            char line[256];
            int n = snprintf(line, sizeof line,
                "{\"v\":1,\"type\":\"imu\",\"t\":%" PRIu32 ",\"dt\":%.4f,\"g\":[%.2f,%.2f,%.2f],\"a\":[%.3f,%.3f,%.3f],"
                "\"h\":%.2f,\"vv\":%.2f,\"dx\":%d,\"dy\":%d,\"bias\":[%.2f,%.2f,%.2f],\"cal\":%d,\"still\":%d}\n",
                t, s.dt, s.gyro_dps[0], s.gyro_dps[1], s.gyro_dps[2], s.accel_g[0], s.accel_g[1], s.accel_g[2],
                h, v, dx, dy, bias[0], bias[1], bias[2], (int)st, still ? 1 : 0);
            if (n > 0 && n < (int)sizeof line) usb_link_telemetry(line, n);
        }
    }
}

static int8_t take8(int32_t *acc)
{
    int32_t v = *acc > 127 ? 127 : (*acc < -127 ? -127 : *acc);
    *acc -= v;   /* 超出部分留到下一帧，不丢失 */
    return (int8_t)v;
}

void app_link(void)
{
    ESP_ERROR_CHECK(bsp_early_init());
    esp_err_t nv = nvs_flash_init();
    if (nv != ESP_OK) ESP_LOGE(TAG, "NVS 初始化失败 %s：参数不保存，也不自动擦除", esp_err_to_name(nv));

    s_lock = xSemaphoreCreateMutex();
    s_events = xQueueCreate(32, AK_WIRE_SIZE);
    ESP_ERROR_CHECK(usb_link_init());
    vTaskDelay(pdMS_TO_TICKS(300));   /* 给电脑一点时间枚举，以便看到下面的启动日志 */
    app_report_identity();

    ak_pointer_cfg pcfg;
    if (!ptr_store_load(&pcfg)) { ak_pointer_default_cfg(&pcfg); ESP_LOGI(TAG, "指向参数：默认值"); }
    else ESP_LOGI(TAG, "指向参数：已从 NVS 读取");
    ak_pointer_init(&s_ptr, &pcfg);

    ak_init(&s_ctrl, esp_random() | 1u, bsp_keys_raw(), now_ms(), on_event, NULL);
    s_ctrl.hardware_faults = FAULT_HAPTIC;   /* 本档未实现，振动命令将返回 INVALID */

    /* I2C 三件套识别：只探测地址，不写寄存器（BQ25180 保持上电默认，不改充电参数） */
    if (bsp_i2c_init() == ESP_OK) {
        ESP_LOGI(TAG, "I2C 探测：BMI270 0x68 %s | BQ25180 0x6A %s | DRV2605L 0x5A %s",
                 bsp_i2c_probe(BSP_I2C_ADDR_BMI270) ? "ACK" : "无应答",
                 bsp_i2c_probe(BSP_I2C_ADDR_BQ25180) ? "ACK" : "无应答",
                 bsp_i2c_probe(BSP_I2C_ADDR_DRV2605L) ? "ACK" : "无应答");
    } else {
        ESP_LOGE(TAG, "I2C 初始化失败");
    }
    xTaskCreatePinnedToCore(imu_task, "imu", 4096, NULL, 10, &s_imu_task, 1);
    if (imu_init(CONFIG_E24_IMU_ODR_HZ, s_imu_task) == ESP_OK) {
        s_imu_ok = true;
        s_imu_go = true;
        xTaskNotifyGive(s_imu_task);
        ESP_LOGI(TAG, "陀螺仪：请静置约 1.2 s 完成上电校准");
    } else {
        s_ctrl.hardware_faults |= FAULT_IMU;
        ESP_LOGE(TAG, "IMU 不可用：保留按键与点击，停用指向");
    }

    esp_err_t audio = audio_svc_init();
    if (audio != ESP_OK) {
        s_ctrl.hardware_faults |= FAULT_AUDIO;
        ESP_LOGE(TAG, "音频初始化失败 %s：录音和提示音不可用", esp_err_to_name(audio));
    }

#if CONFIG_E24_MIC_POC_OPEN
    ESP_LOGW(TAG, "POC 档：主机开流即放行麦克风，隐私闸门 AUD 02 已放宽，仅限台架");
#endif

    ak_devcfg_io io = {NULL, cfg_save, cfg_calibrate, cfg_telemetry, cfg_download, audio == ESP_OK ? cfg_audio : NULL};
    uint8_t reply[32], pending[AK_WIRE_SIZE];
    bool reply_pending = false, pending_valid = false, download_after = false;
    uint8_t last_hid = 0xff, last_buttons = s_ctrl.buttons;
    bool was_mounted = false, was_cal = false;
    uint32_t last_status = 0, last_motion = 0;

    for (;;) {
        uint32_t t = now_ms();
        bool mounted = usb_link_mounted();
        if (was_mounted && !mounted) {        /* 断连：释放输入、新 session，不重放 */
            ak_disconnect(&s_ctrl, t);
            usb_link_flush();
            xQueueReset(s_events);
            reply_pending = pending_valid = false;
            last_hid = 0xff;
            xSemaphoreTake(s_lock, portMAX_DELAY); s_acc_x = s_acc_y = 0; ak_pointer_recenter(&s_ptr); xSemaphoreGive(s_lock);
        }
        was_mounted = mounted;
        if (!mounted) { xSemaphoreTake(s_lock, portMAX_DELAY); s_acc_x = s_acc_y = 0; ak_pointer_recenter(&s_ptr); xSemaphoreGive(s_lock); }

        ak_poll(&s_ctrl, bsp_keys_raw(), t);
        if (s_ctrl.buttons != last_buttons) {  /* 点击稳定 */
            last_buttons = s_ctrl.buttons;
            xSemaphoreTake(s_lock, portMAX_DELAY); ak_pointer_button_edge(&s_ptr, t); xSemaphoreGive(s_lock);
        }
        if (!s_imu_ok && !(s_ctrl.hardware_faults & FAULT_IMU)) { s_ctrl.hardware_faults |= FAULT_IMU; ak_fault(&s_ctrl, 2, t); }
        bool cal = ak_pointer_calibrated(&s_ptr);
        s_ctrl.calibrated = cal;
        if (cal != was_cal) { was_cal = cal; ESP_LOGI(TAG, "陀螺仪%s", cal ? "已校准" : "未校准"); }
        if (usb_link_take_overflow()) ak_fault(&s_ctrl, 1, t);

        ak_wire_command cmd;
        while (usb_link_pop_command(&cmd)) {
            if (!mounted) continue;
            ak_result r = ak_command(&s_ctrl, cmd.session, cmd.sequence, cmd.command, cmd.value, t);
            if (cmd.command == AK_RECENTER && r == AK_OK) {
                xSemaphoreTake(s_lock, portMAX_DELAY); ak_pointer_recenter(&s_ptr); s_acc_x = s_acc_y = 0; xSemaphoreGive(s_lock);
            }
        }

        /* 隐私闸门：控制核心已在本轮处理完松键/租约/断连，结果立即生效 */
        if (audio == ESP_OK) {
            bool mic_power = s_ctrl.mic_power, mic_open = ak_mic_permitted(&s_ctrl);
#if CONFIG_E24_MIC_POC_OPEN
            /* POC 档放宽 AUD 02：主机开流即放行，关流即关；采集故障后不再放行 */
            mic_power = mic_open = audio_svc_streaming() && !(s_ctrl.hardware_faults & FAULT_AUDIO);
#endif
            audio_svc_set_mic(mic_power, mic_open);
            bool capture_failed = false;
            if (audio_svc_take_abort(&capture_failed)) {
                ak_mic_abort(&s_ctrl, t);
                audio_svc_set_mic(false, false);
                if (capture_failed) { s_ctrl.hardware_faults |= FAULT_AUDIO; ak_fault(&s_ctrl, 3, t); }
            }
        }

        if (mounted && !reply_pending) {
            uint8_t req[32];
            if (usb_link_pop_config(req)) {
                if (ak_devcfg_owns(req, 32)) {
                    xSemaphoreTake(s_lock, portMAX_DELAY);
                    ak_pointer_cfg c = s_ptr.cfg;
                    uint8_t st = (uint8_t)s_ptr.state;
                    xSemaphoreGive(s_lock);
                    bool apply = false;
                    ak_devcfg_process(&c, st, s_telemetry, s_ctrl.session, req, 32, io, reply, &apply, &download_after);
                    if (apply) { xSemaphoreTake(s_lock, portMAX_DELAY); ak_pointer_set_cfg(&s_ptr, &c); xSemaphoreGive(s_lock); }
                    reply_pending = true;
                } else {
                    ESP_LOGW(TAG, "配置操作 0x%02X 本档不支持（REV A Wi-Fi/BLE 配置未移植）", req[1]);
                }
            }
        }

        if (mounted && usb_link_ready()) {
            if (reply_pending) {
                if (usb_link_config_reply(reply)) {
                    reply_pending = false;
                    if (download_after) cfg_download(NULL);
                }
            } else if (pending_valid || xQueueReceive(s_events, pending, 0) == pdTRUE) {
                pending_valid = !usb_link_state(pending);
            } else if (last_hid != s_ctrl.hid_buttons) {
                if (usb_link_mouse(s_ctrl.hid_buttons, 0, 0)) last_hid = s_ctrl.hid_buttons;
            } else if (t - last_status >= 100) {   /* 周期状态：电脑端靠它拿 session 与标志位 */
                ak_encode_state(&s_ctrl, NULL, pending);
                pending_valid = !usb_link_state(pending);
                last_status = t;
            } else {
                xSemaphoreTake(s_lock, portMAX_DELAY);
                int32_t ax = s_acc_x, ay = s_acc_y;
                bool host = s_ctrl.owner == AK_HOST;
                bool allowed = ak_pointer_allowed(&s_ctrl);
                if (!host && !allowed) { s_acc_x = s_acc_y = 0; ax = ay = 0; }   /* 录音/圈画中：丢弃，不攒 */
                xSemaphoreGive(s_lock);
                if ((ax || ay) && host && t - last_motion >= 4) {
                    int16_t x = (int16_t)(ax > 32767 ? 32767 : ax < -32767 ? -32767 : ax);
                    int16_t y = (int16_t)(ay > 32767 ? 32767 : ay < -32767 ? -32767 : ay);
                    uint8_t pkt[AK_WIRE_SIZE];
                    ak_encode_motion(&s_ctrl, x, y, pkt);
                    if (usb_link_state(pkt)) {
                        xSemaphoreTake(s_lock, portMAX_DELAY); s_acc_x -= x; s_acc_y -= y; xSemaphoreGive(s_lock);
                        last_motion = t;
                    }
                } else if ((ax || ay) && allowed) {
                    xSemaphoreTake(s_lock, portMAX_DELAY);
                    int8_t x = take8(&s_acc_x), y = take8(&s_acc_y);
                    xSemaphoreGive(s_lock);
                    if (!usb_link_mouse(s_ctrl.hid_buttons, x, y)) {
                        xSemaphoreTake(s_lock, portMAX_DELAY); s_acc_x += x; s_acc_y += y; xSemaphoreGive(s_lock);
                    }
                }
            }
        }
        vTaskDelay(1);
    }
}
