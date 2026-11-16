#include "bsp_i2c.h"
#include "bsp_pins.h"
#include "esp_log.h"

static const char *TAG = "bsp_i2c";
static i2c_master_bus_handle_t s_bus;

esp_err_t bsp_i2c_init(void)
{
    if (s_bus) return ESP_OK;
    const i2c_master_bus_config_t cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = BSP_PIN_I2C_SDA,
        .scl_io_num = BSP_PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false,   /* 板上 R1/R2 4.7k */
    };
    esp_err_t err = i2c_new_master_bus(&cfg, &s_bus);
    if (err == ESP_OK) ESP_LOGI(TAG, "I2C SDA=%d SCL=%d %u Hz", BSP_PIN_I2C_SDA, BSP_PIN_I2C_SCL, (unsigned)BSP_I2C_FREQ_HZ);
    return err;
}

i2c_master_bus_handle_t bsp_i2c_bus(void) { return s_bus; }

esp_err_t bsp_i2c_add(uint8_t addr7, i2c_master_dev_handle_t *dev)
{
    const i2c_device_config_t d = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr7,
        .scl_speed_hz = BSP_I2C_FREQ_HZ,
    };
    return i2c_master_bus_add_device(s_bus, &d, dev);
}

bool bsp_i2c_probe(uint8_t addr7)
{
    return s_bus && i2c_master_probe(s_bus, addr7, BSP_I2C_TIMEOUT_MS) == ESP_OK;
}
