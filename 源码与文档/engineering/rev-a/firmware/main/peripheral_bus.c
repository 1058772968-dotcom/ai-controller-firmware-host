#include "peripheral_bus.h"
#include "board_config.h"
#include "driver/i2c.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
static bool read_bus(void *ctx,uint8_t addr,uint8_t reg,uint8_t *data,size_t n) {
    (void)ctx;return i2c_master_write_read_device(I2C_NUM_0,addr,&reg,1,data,n,pdMS_TO_TICKS(4))==ESP_OK;
}
static bool write_bus(void *ctx,uint8_t addr,uint8_t reg,const uint8_t *data,size_t n) {
    (void)ctx;if(n>8)return false;uint8_t bytes[9];bytes[0]=reg;
    for(size_t i=0;i<n;i++)bytes[i+1]=data[i];
    return i2c_master_write_to_device(I2C_NUM_0,addr,bytes,n+1,pdMS_TO_TICKS(4))==ESP_OK;
}
static void enable(void *ctx,bool on) {(void)ctx;gpio_set_level(AK_PIN_HAPTIC_EN,on);}
esp_err_t ak_peripheral_bus_init(ak_i2c_io *io) {
    i2c_config_t c={.mode=I2C_MODE_MASTER,.sda_io_num=AK_PIN_I2C_SDA,.scl_io_num=AK_PIN_I2C_SCL,
        .sda_pullup_en=GPIO_PULLUP_DISABLE,.scl_pullup_en=GPIO_PULLUP_DISABLE,.master.clk_speed=400000};
    esp_err_t e=i2c_param_config(I2C_NUM_0,&c);if(e!=ESP_OK)return e;
    e=i2c_driver_install(I2C_NUM_0,I2C_MODE_MASTER,0,0,0);if(e!=ESP_OK)return e;
    *io=(ak_i2c_io){.read=read_bus,.write=write_bus,.enable_haptic=enable};return ESP_OK;
}
