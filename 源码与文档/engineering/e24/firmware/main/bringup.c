/* E24 M1 点亮程序：只验证板级基础，不启用 I2C、I2S、USB 设备栈和无线。
 * 日志走 USB-Serial-JTAG（idf.py monitor）。验证项见 engineering/e24/README.md 的 M1 清单。 */
#include <inttypes.h>
#include "app.h"
#include "bsp_e24.h"
#include "controller.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "e24-bringup";

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static const char *event_name(uint8_t type)
{
    static const char *names[] = {"?", "EDGE", "OWNER", "MIC", "DRAW_STATE", "HAPTIC",
                                  "RESET_INPUT", "CENTER", "ACK", "FAULT"};
    return type < sizeof names / sizeof names[0] ? names[type] : "?";
}

/* 控制核心发出的事件：M1 只打印，用来确认去抖和“启动时按住的键要先松开”规则在真机上生效。 */
static void on_event(void *ctx, const ak_event *e)
{
    (void)ctx;
    ESP_LOGI(TAG, "事件 %-11s 键位 0x%X 值 %u 序号 %" PRIu32 " t=%" PRIu32 "ms",
             event_name(e->type), e->buttons, e->value, e->sequence, e->time_ms);
}

void app_report_identity(void)
{
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    const esp_app_desc_t *app = esp_app_get_description();
    const esp_partition_t *run = esp_ota_get_running_partition();
    ESP_LOGI(TAG, "板型 %s | 固件 %s %s | IDF %s", BSP_BOARD_REVISION, app->project_name, app->version, app->idf_ver);
    ESP_LOGI(TAG, "芯片 ESP32-S3 rev v%d.%d，%d 核 | 运行分区 %s @0x%" PRIx32,
             chip.revision / 100, chip.revision % 100, chip.cores, run ? run->label : "?", run ? run->address : 0);
    ESP_LOGI(TAG, "复位原因：%s", bsp_reset_reason_str(esp_reset_reason()));

    uint32_t flash = 0, psram = 0;
    esp_err_t err = bsp_check_memory(&flash, &psram);
    ESP_LOGI(TAG, "Flash %" PRIu32 " KB，PSRAM %" PRIu32 " KB -> %s",
             flash / 1024, psram / 1024, err == ESP_OK ? "PASS" : "FAIL");
}

void app_bringup(void)
{
    ESP_ERROR_CHECK(bsp_early_init());
    app_report_identity();

    uint8_t raw = bsp_keys_raw();
    bool vbus = bsp_vbus_present();
    if (raw) {
        ESP_LOGW(TAG, "启动时有键按住 0x%X：松开前不会产生动作", raw);
    }
    ESP_LOGI(TAG, "VBUS %s", vbus ? "存在" : "不存在");

    static ak_controller ctrl;
    ak_init(&ctrl, esp_random(), raw, now_ms(), on_event, NULL);

    uint8_t last_raw = raw;
    uint32_t last_beat = now_ms();
    for (;;) {
        uint32_t t = now_ms();
        raw = bsp_keys_raw();
        if (raw != last_raw) {
            ESP_LOGD(TAG, "原始电平 0x%X -> 0x%X t=%" PRIu32 "ms", last_raw, raw, t);
            last_raw = raw;
        }
        ak_poll(&ctrl, raw, t);

        bool v = bsp_vbus_present();
        if (v != vbus) {
            vbus = v;
            ESP_LOGI(TAG, "VBUS %s t=%" PRIu32 "ms", vbus ? "插入" : "拔出", t);
        }

        if (t - last_beat >= 5000) {
            last_beat = t;
            ESP_LOGI(TAG, "心跳 键位 0x%X | 内部堆 %u KB | PSRAM 空闲 %u KB", ctrl.buttons,
                     (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
                     (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}
