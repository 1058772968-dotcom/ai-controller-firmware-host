#include "bsp_e24.h"
#include "driver/gpio.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_psram.h"

static const char *TAG = "bsp";

typedef struct { gpio_num_t pin; int level; } boot_output_t;

esp_err_t bsp_early_init(void)
{
    /* 1. 输出脚：先写电平再切方向，避免切换瞬间出现高电平毛刺。
     *    AMP_EN 低 = MAX98357A SD_MODE 关断；I2S 三根线静止为低。 */
    static const boot_output_t outs[] = BSP_BOOT_OUTPUTS;
    uint64_t out_mask = 0;
    for (size_t i = 0; i < sizeof outs / sizeof outs[0]; i++) {
        ESP_ERROR_CHECK(gpio_set_level(outs[i].pin, outs[i].level));
        out_mask |= 1ULL << outs[i].pin;
    }
    const gpio_config_t out_cfg = {
        .pin_bit_mask = out_mask,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&out_cfg));
    for (size_t i = 0; i < sizeof outs / sizeof outs[0]; i++) {
        ESP_ERROR_CHECK(gpio_set_level(outs[i].pin, outs[i].level));
    }

    /* 2. 有外部上拉/下拉的输入：按键 R10–R13、CHG_INT R4、VBUS R19、MIC_DOUT R3 下拉。 */
    const gpio_config_t in_cfg = {
        .pin_bit_mask = (1ULL << BSP_PIN_KEY_LEFT) | (1ULL << BSP_PIN_KEY_RIGHT) |
                        (1ULL << BSP_PIN_KEY_VOICE) | (1ULL << BSP_PIN_KEY_DRAW) |
                        (1ULL << BSP_PIN_CHG_INT_N) | (1ULL << BSP_PIN_USB_VBUS_PRESENT) |
                        (1ULL << BSP_PIN_MIC_DOUT),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&in_cfg));

    /* 3. IMU_INT 没有外部上拉；BMI270 驱动配置成推挽前先用内部下拉避免悬空。 */
    const gpio_config_t imu_cfg = {
        .pin_bit_mask = 1ULL << BSP_PIN_IMU_INT,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&imu_cfg));

    ESP_LOGI(TAG, "%s 安全初始态：AMP_EN=0，I2S 静止，输入脚就绪", BSP_BOARD_REVISION);
    return ESP_OK;
}

uint8_t bsp_keys_raw(void)
{
    static const gpio_num_t keys[] = BSP_KEY_PINS;
    uint8_t mask = 0;
    for (unsigned i = 0; i < sizeof keys / sizeof keys[0]; i++) {
        if (gpio_get_level(keys[i]) == 0) {  /* 低有效 */
            mask |= (uint8_t)(1u << i);
        }
    }
    return mask;
}

bool bsp_vbus_present(void)
{
    return gpio_get_level(BSP_PIN_USB_VBUS_PRESENT) != 0;
}

esp_err_t bsp_check_memory(uint32_t *flash_bytes, uint32_t *psram_bytes)
{
    uint32_t flash = 0;
    esp_err_t err = esp_flash_get_size(NULL, &flash);
    size_t psram = esp_psram_is_initialized() ? esp_psram_get_size() : 0;
    if (flash_bytes) *flash_bytes = flash;
    if (psram_bytes) *psram_bytes = (uint32_t)psram;
    if (err != ESP_OK) return err;
    if (flash != BSP_FLASH_BYTES || psram != BSP_PSRAM_BYTES) {
        ESP_LOGE(TAG, "容量不符：Flash %lu/%u，PSRAM %u/%u",
                 (unsigned long)flash, BSP_FLASH_BYTES, (unsigned)psram, BSP_PSRAM_BYTES);
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}

const char *bsp_reset_reason_str(esp_reset_reason_t r)
{
    switch (r) {
    case ESP_RST_POWERON:   return "上电";
    case ESP_RST_EXT:       return "外部复位";
    case ESP_RST_SW:        return "软件复位";
    case ESP_RST_PANIC:     return "异常崩溃";
    case ESP_RST_INT_WDT:   return "中断看门狗";
    case ESP_RST_TASK_WDT:  return "任务看门狗";
    case ESP_RST_WDT:       return "其他看门狗";
    case ESP_RST_DEEPSLEEP: return "深睡唤醒";
    case ESP_RST_BROWNOUT:  return "掉电保护";
    case ESP_RST_USB:       return "USB 复位";
    case ESP_RST_JTAG:      return "JTAG 复位";
    default:                return "未知";
    }
}
