#include "imu_bmi270.h"
#include <string.h>
#include "bmi270.h"
#include "bsp_i2c.h"
#include "bsp_pins.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_rom_sys.h"

static const char *TAG = "imu";
#define RW_LEN 128                 /* 配置文件按此长度分块写入 */
#define GYRO_LSB_PER_DPS (32768.0f / 2000.0f)
#define ACC_LSB_PER_G (32768.0f / 4.0f)
#define SENSOR_TIME_TICK_S 39.0625e-6f

static i2c_master_dev_handle_t s_dev;
static struct bmi2_dev s_bmi;
static TaskHandle_t s_notify;
static uint32_t s_last_time;
static bool s_have_time;

static BMI2_INTF_RETURN_TYPE rd(uint8_t reg, uint8_t *data, uint32_t len, void *ctx)
{
    (void)ctx;
    return i2c_master_transmit_receive(s_dev, &reg, 1, data, len, BSP_I2C_TIMEOUT_MS) == ESP_OK ? BMI2_INTF_RET_SUCCESS : -1;
}

static BMI2_INTF_RETURN_TYPE wr(uint8_t reg, const uint8_t *data, uint32_t len, void *ctx)
{
    (void)ctx;
    static uint8_t buf[RW_LEN + 1];
    if (len > RW_LEN) return -1;
    buf[0] = reg;
    memcpy(buf + 1, data, len);
    for (int attempt = 0; attempt <= BSP_I2C_RETRIES; attempt++)
        if (i2c_master_transmit(s_dev, buf, len + 1, BSP_I2C_TIMEOUT_MS) == ESP_OK) return BMI2_INTF_RET_SUCCESS;
    return -1;
}

static void delay_us(uint32_t us, void *ctx)
{
    (void)ctx;
    if (us >= 1000) vTaskDelay(pdMS_TO_TICKS((us + 999) / 1000));
    else esp_rom_delay_us(us);
}

static void IRAM_ATTR on_drdy(void *arg)
{
    (void)arg;
    BaseType_t woken = pdFALSE;
    if (s_notify) vTaskNotifyGiveFromISR(s_notify, &woken);
    portYIELD_FROM_ISR(woken);
}

static uint8_t odr_code(uint16_t hz, bool gyro)
{
    if (hz >= 800) return gyro ? BMI2_GYR_ODR_800HZ : BMI2_ACC_ODR_800HZ;
    if (hz >= 400) return gyro ? BMI2_GYR_ODR_400HZ : BMI2_ACC_ODR_400HZ;
    if (hz >= 200) return gyro ? BMI2_GYR_ODR_200HZ : BMI2_ACC_ODR_200HZ;
    return gyro ? BMI2_GYR_ODR_100HZ : BMI2_ACC_ODR_100HZ;
}

uint8_t imu_chip_id(void) { return s_bmi.chip_id; }

esp_err_t imu_init(uint16_t odr_hz, TaskHandle_t notify_task)
{
    esp_err_t err = bsp_i2c_add(BSP_I2C_ADDR_BMI270, &s_dev);
    if (err != ESP_OK) return err;
    memset(&s_bmi, 0, sizeof s_bmi);
    s_bmi.intf = BMI2_I2C_INTF;
    s_bmi.read = rd;
    s_bmi.write = wr;
    s_bmi.delay_us = delay_us;
    s_bmi.read_write_len = RW_LEN;
    s_bmi.config_file_ptr = NULL;   /* 用 SensorAPI 自带配置文件 */

    int8_t r = bmi270_init(&s_bmi);  /* 含软复位、配置文件装载与 INTERNAL_STATUS 检查 */
    if (r != BMI2_OK) {
        ESP_LOGE(TAG, "bmi270_init 失败 %d（chip_id=0x%02X）", r, s_bmi.chip_id);
        return ESP_FAIL;
    }

    struct bmi2_sens_config c[2] = {{.type = BMI2_ACCEL}, {.type = BMI2_GYRO}};
    if (bmi2_get_sensor_config(c, 2, &s_bmi) != BMI2_OK) return ESP_FAIL;
    c[0].cfg.acc.odr = odr_code(odr_hz, false);
    c[0].cfg.acc.range = BMI2_ACC_RANGE_4G;
    c[0].cfg.acc.bwp = BMI2_ACC_NORMAL_AVG4;
    c[0].cfg.acc.filter_perf = BMI2_PERF_OPT_MODE;
    c[1].cfg.gyr.odr = odr_code(odr_hz, true);
    c[1].cfg.gyr.range = BMI2_GYR_RANGE_2000;
    c[1].cfg.gyr.ois_range = BMI2_GYR_OIS_2000;
    c[1].cfg.gyr.bwp = BMI2_GYR_NORMAL_MODE;
    c[1].cfg.gyr.noise_perf = BMI2_PERF_OPT_MODE;
    c[1].cfg.gyr.filter_perf = BMI2_PERF_OPT_MODE;
    if (bmi2_set_sensor_config(c, 2, &s_bmi) != BMI2_OK) return ESP_FAIL;

    /* INT1：推挽、高有效、非锁存，数据就绪 */
    struct bmi2_int_pin_config pin = {0};
    pin.pin_type = BMI2_INT1;
    pin.int_latch = BMI2_INT_NON_LATCH;
    pin.pin_cfg[0].lvl = BMI2_INT_ACTIVE_HIGH;
    pin.pin_cfg[0].od = BMI2_INT_PUSH_PULL;
    pin.pin_cfg[0].output_en = BMI2_INT_OUTPUT_ENABLE;
    pin.pin_cfg[0].input_en = BMI2_INT_INPUT_DISABLE;
    if (bmi2_set_int_pin_config(&pin, &s_bmi) != BMI2_OK) return ESP_FAIL;
    if (bmi2_map_data_int(BMI2_DRDY_INT, BMI2_INT1, &s_bmi) != BMI2_OK) return ESP_FAIL;

    const uint8_t sens[2] = {BMI2_ACCEL, BMI2_GYRO};
    if (bmi2_sensor_enable(sens, 2, &s_bmi) != BMI2_OK) return ESP_FAIL;

    s_notify = notify_task;
    if (notify_task) {
        /* 推挽已配置，去掉 BSP 里临时加的内部下拉 */
        gpio_set_pull_mode(BSP_PIN_IMU_INT, GPIO_FLOATING);
        gpio_set_intr_type(BSP_PIN_IMU_INT, GPIO_INTR_POSEDGE);
        esp_err_t e = gpio_install_isr_service(0);
        if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) return e;
        ESP_ERROR_CHECK(gpio_isr_handler_add(BSP_PIN_IMU_INT, on_drdy, NULL));
        gpio_intr_enable(BSP_PIN_IMU_INT);
    }
    s_have_time = false;
    ESP_LOGI(TAG, "BMI270 就绪 chip_id=0x%02X ODR≈%u Hz ±4g ±2000dps", s_bmi.chip_id, (unsigned)odr_hz);
    return ESP_OK;
}

esp_err_t imu_read(imu_sample_t *o)
{
    struct bmi2_sens_data d = {0};
    if (bmi2_get_sensor_data(&d, &s_bmi) != BMI2_OK) return ESP_FAIL;
    o->gyro_dps[0] = d.gyr.x / GYRO_LSB_PER_DPS;
    o->gyro_dps[1] = d.gyr.y / GYRO_LSB_PER_DPS;
    o->gyro_dps[2] = d.gyr.z / GYRO_LSB_PER_DPS;
    o->accel_g[0] = d.acc.x / ACC_LSB_PER_G;
    o->accel_g[1] = d.acc.y / ACC_LSB_PER_G;
    o->accel_g[2] = d.acc.z / ACC_LSB_PER_G;
    o->sensor_time = d.sens_time;
    uint32_t delta = (d.sens_time - s_last_time) & 0xFFFFFFu;   /* 24 位计数，39.0625 µs/计 */
    o->dt = s_have_time ? delta * SENSOR_TIME_TICK_S : 0.0f;
    s_last_time = d.sens_time;
    s_have_time = true;
    return ESP_OK;
}
