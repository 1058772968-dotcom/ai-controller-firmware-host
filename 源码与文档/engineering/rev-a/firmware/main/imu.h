#pragma once
#include "esp_err.h"
#include <stdbool.h>
esp_err_t ak_imu_init(void);
esp_err_t ak_imu_read(float gyro_dps[3],float accel_g[3],bool *fresh);
