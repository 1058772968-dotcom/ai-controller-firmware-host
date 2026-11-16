#pragma once
/* BMI270 驱动（L2）：Bosch SensorAPI + i2c_master。数据就绪中断 INT1→GPIO10（推挽、高有效）。 */
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef struct {
    float gyro_dps[3];   /* 传感器坐标，°/s */
    float accel_g[3];    /* 传感器坐标，g */
    float dt;            /* 与上一帧的间隔（来自传感器时间戳），秒；首帧为 0 */
    uint32_t sensor_time;
} imu_sample_t;

/* 复位、装配置文件、确认 INTERNAL_STATUS、配置 ±4g/±2000dps/ODR，开数据就绪中断。
 * notify_task：数据就绪时被 xTaskNotifyGive 唤醒的任务（可为 NULL，改用轮询）。 */
esp_err_t imu_init(uint16_t odr_hz, TaskHandle_t notify_task);
esp_err_t imu_read(imu_sample_t *out);
uint8_t imu_chip_id(void);
