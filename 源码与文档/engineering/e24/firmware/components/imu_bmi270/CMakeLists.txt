idf_component_register(SRCS "imu_bmi270.c"
                       INCLUDE_DIRS "include"
                       REQUIRES bsp_e24 bmi270_sensorapi driver esp_timer freertos)
