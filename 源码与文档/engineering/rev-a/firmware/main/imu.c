#include "imu.h"
#include "board_config.h"
#include "lsm6dsv16x_reg.h"
#include "driver/spi_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
static spi_device_handle_t imu;
static int32_t write_reg(void *handle,uint8_t reg,const uint8_t *data,uint16_t len) {
    (void)handle;
    spi_transaction_t t={.cmd=reg & 0x7f,.length=len*8,.tx_buffer=data};
    return spi_device_polling_transmit(imu,&t)==ESP_OK?0:-1;
}
static int32_t read_reg(void *handle,uint8_t reg,uint8_t *data,uint16_t len) {
    (void)handle;
    spi_transaction_t t={.cmd=reg|0x80,.length=len*8,.rxlength=len*8,.rx_buffer=data};
    return spi_device_polling_transmit(imu,&t)==ESP_OK?0:-1;
}
static void delay_ms(uint32_t ms) {vTaskDelay(pdMS_TO_TICKS(ms));}
static stmdev_ctx_t ctx={.write_reg=write_reg,.read_reg=read_reg,.mdelay=delay_ms};
esp_err_t ak_imu_init(void) {
    spi_bus_config_t bus={.mosi_io_num=AK_PIN_IMU_MOSI,.miso_io_num=AK_PIN_IMU_MISO,.sclk_io_num=AK_PIN_IMU_SCLK,.quadwp_io_num=-1,.quadhd_io_num=-1,.max_transfer_sz=32};
    esp_err_t e=spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO);if(e!=ESP_OK)return e;
    spi_device_interface_config_t dev={.command_bits=8,.mode=3,.clock_speed_hz=8000000,.spics_io_num=AK_PIN_IMU_CS,.queue_size=1};
    e=spi_bus_add_device(SPI2_HOST,&dev,&imu);if(e!=ESP_OK)return e;
    uint8_t id=0;
    if(lsm6dsv16x_device_id_get(&ctx,&id)||id!=LSM6DSV16X_ID)return ESP_ERR_NOT_FOUND;
    if(lsm6dsv16x_sw_reset(&ctx))return ESP_FAIL;
    if(lsm6dsv16x_block_data_update_set(&ctx,1)||lsm6dsv16x_xl_full_scale_set(&ctx,LSM6DSV16X_4g)||lsm6dsv16x_gy_full_scale_set(&ctx,LSM6DSV16X_2000dps)||lsm6dsv16x_xl_data_rate_set(&ctx,LSM6DSV16X_ODR_AT_240Hz)||lsm6dsv16x_gy_data_rate_set(&ctx,LSM6DSV16X_ODR_AT_240Hz))return ESP_FAIL;
    return ESP_OK;
}
esp_err_t ak_imu_read(float g[3],float a[3],bool *fresh) {
    *fresh=false;lsm6dsv16x_data_ready_t ready={0};
    if(lsm6dsv16x_flag_data_ready_get(&ctx,&ready))return ESP_FAIL;
    if(!ready.drdy_xl||!ready.drdy_gy)return ESP_OK;
    int16_t raw_g[3],raw_a[3];
    if(lsm6dsv16x_angular_rate_raw_get(&ctx,raw_g)||lsm6dsv16x_acceleration_raw_get(&ctx,raw_a))return ESP_FAIL;
    for(unsigned i=0;i<3;i++) {g[i]=lsm6dsv16x_from_fs2000_to_mdps(raw_g[i])*.001f;a[i]=lsm6dsv16x_from_fs4_to_mg(raw_a[i])*.001f;}
    *fresh=true;return ESP_OK;
}
