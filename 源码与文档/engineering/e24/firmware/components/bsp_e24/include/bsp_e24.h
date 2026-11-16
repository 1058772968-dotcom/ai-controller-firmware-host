#pragma once
/* E24 板级支持包（L1）。只描述“这块板怎么接线、上电是什么状态”，不含器件协议。 */
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_system.h"
#include "bsp_pins.h"

#ifdef __cplusplus
extern "C" {
#endif

/* app_main 第一行调用：功放关、I2S 线拉低、按键/中断脚设为输入。可重复调用。 */
esp_err_t bsp_early_init(void);

/* 四键原始电平，按下为 1：bit0 L, bit1 R, bit2 V, bit3 S(DRAW)。未去抖。 */
uint8_t bsp_keys_raw(void);

/* GPIO15：TPS3808 判定 VBUS 高于门限时为 true。未去抖。 */
bool bsp_vbus_present(void);

/* 校验 Flash 与 PSRAM 实际容量是否等于 board.json 声明值。 */
esp_err_t bsp_check_memory(uint32_t *flash_bytes, uint32_t *psram_bytes);

const char *bsp_reset_reason_str(esp_reset_reason_t reason);

#ifdef __cplusplus
}
#endif
