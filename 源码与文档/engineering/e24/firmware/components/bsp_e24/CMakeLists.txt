idf_component_register(SRCS "bsp_e24.c" "bsp_i2c.c"
                       INCLUDE_DIRS "include"
                       REQUIRES driver esp_system esp_hw_support esp_psram spi_flash esp_timer)
