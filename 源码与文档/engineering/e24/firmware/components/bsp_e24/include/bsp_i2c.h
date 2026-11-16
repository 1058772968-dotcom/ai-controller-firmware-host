#pragma once
/* E24 I2C 总线（GPIO8/9，外部 4.7k 上拉）。IDF 5.2 新驱动 i2c_master；不要与旧 i2c 驱动混用。 */
#include <stdbool.h>
#include <stdint.h>
#include "driver/i2c_master.h"
#include "esp_err.h"

esp_err_t bsp_i2c_init(void);
i2c_master_bus_handle_t bsp_i2c_bus(void);
esp_err_t bsp_i2c_add(uint8_t addr7, i2c_master_dev_handle_t *dev);
/* 只发地址看 ACK，不读写寄存器 */
bool bsp_i2c_probe(uint8_t addr7);
