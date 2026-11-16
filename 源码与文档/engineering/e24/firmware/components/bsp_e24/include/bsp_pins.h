/* 由 tools/gen_board.py 从 spec/board.json 生成，不要手改。 */
#pragma once
#define BSP_BOARD_REVISION "AIKEY-E24"
#define BSP_FLASH_BYTES 8388608u
#define BSP_PSRAM_BYTES 8388608u

#define BSP_PIN_I2S_BCLK 4 /* net I2S_BCLK, out */
#define BSP_PIN_I2S_WS 5 /* net I2S_WS, out */
#define BSP_PIN_MIC_DOUT 6 /* net MIC_DOUT, in */
#define BSP_PIN_SPK_DIN 7 /* net SPK_DIN, out */
#define BSP_PIN_I2C_SDA 8 /* net I2C_SDA, od */
#define BSP_PIN_I2C_SCL 9 /* net I2C_SCL, od */
#define BSP_PIN_IMU_INT 10 /* net IMU_INT, in */
#define BSP_PIN_CHG_INT_N 11 /* net CHG_INT, in, active low */
#define BSP_PIN_KEY_LEFT 12 /* net KEY_LEFT, in, active low */
#define BSP_PIN_KEY_RIGHT 13 /* net KEY_RIGHT, in, active low */
#define BSP_PIN_KEY_VOICE 14 /* net KEY_VOICE, in, active low */
#define BSP_PIN_USB_VBUS_PRESENT 15 /* net USB_VBUS_PRESENT, in */
#define BSP_PIN_AMP_EN 16 /* net AMP_EN, out */
#define BSP_PIN_USB_DM 19 /* net USB_D_MINUS_MCU, usb */
#define BSP_PIN_USB_DP 20 /* net USB_D_PLUS_MCU, usb */
#define BSP_PIN_KEY_DRAW 21 /* net KEY_DRAW, in, active low */
#define BSP_PIN_BOOT_N 0 /* net BOOT_N, strap */

/* 上电安全态：这些输出在 bsp_early_init() 里第一时间驱动到给定电平 */
#define BSP_BOOT_OUTPUTS { {BSP_PIN_I2S_BCLK, 0}, {BSP_PIN_I2S_WS, 0}, {BSP_PIN_SPK_DIN, 0}, {BSP_PIN_AMP_EN, 0} }
/* 按键顺序与控制核心位图一致：bit0 L, bit1 R, bit2 V, bit3 S(DRAW) */
#define BSP_KEY_PINS { BSP_PIN_KEY_LEFT, BSP_PIN_KEY_RIGHT, BSP_PIN_KEY_VOICE, BSP_PIN_KEY_DRAW }

#define BSP_I2C_FREQ_HZ 100000u
#define BSP_I2C_TIMEOUT_MS 20
#define BSP_I2C_RETRIES 2
#define BSP_I2C_ADDR_BMI270 0x68 /* 7 位地址 */
#define BSP_I2C_ADDR_BQ25180 0x6A /* 7 位地址 */
#define BSP_I2C_ADDR_DRV2605L 0x5A /* 7 位地址 */
#define BSP_I2S_SAMPLE_HZ 32000u
#define BSP_I2S_SLOT_BITS 32u
#define BSP_PCM_OUTPUT_HZ 16000u
