idf_component_register(SRCS "app_main.c" "bringup.c" "link_app.c" "usb_link.c" "ptr_store.c" "audio_svc.c"
                       INCLUDE_DIRS "."
                       REQUIRES driver bsp_e24 aikey_core imu_bmi270 esp_timer esp_hw_support app_update
                                esp_app_format nvs_flash esp_tinyusb esp_system soc)
